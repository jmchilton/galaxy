"""Run jobs as plain GA4GH TES tasks, with no Pulsar inside the task.

Prototype of "design B" from the galaxy-wes-tes investigation. Each job becomes one
TES task that any spec-following TES server can run:

- TES ``inputs`` fetch every file the job reads from Galaxy's job files API
  (``GET /api/jobs/{id}/files?path=...&job_token=...``): input datasets with their
  metadata and extra files, every file of the job directory (job script, tool
  script, config files) and the tool directory (only the files the job refers
  to when it is large).
- One executor runs Galaxy's own job script in the tool's container. Paths inside
  the container are Galaxy's absolute paths, as on the Kubernetes runner, so the
  command line needs no rewriting.
- TES ``outputs`` send the output datasets, tool stdout/stderr, the exit code
  file and the core job metrics files back to the same API: multipart ``POST``
  (tesp-api) or raw ``PUT`` (Funnel, TESK) to the same URL.
- Each URL carries its own signed token (``galaxy.security.job_files_tokens``),
  valid for one path, one direction (read for inputs, write for outputs), until
  the job ends or ``job_files_token_ttl`` passes. The job's ``job_key``, which
  opens every file of the job, never reaches the TES server.
- Galaxy learns the task's state by polling the TES server, then sets metadata
  and finishes the job locally.

``galaxy.jobs.runners.util.tes_staging`` builds the task from the job's paths;
this module runs it.

With ``tes_directory_outputs: true`` on the destination, the tool working
directory and each output's extra files directory also go back as TES
``DIRECTORY`` outputs, so discovered outputs, ``galaxy.json`` and output
``extra_files`` work. Funnel and TESK upload each file with a PUT to the output
URL's path plus ``/<relative path>``; tesp-api posts every file to the same URL,
which Galaxy can't place, so leave it off there.

Requirements: ``outputs_to_working_directory: true`` on the destination (every
file the job writes is then in its job directory), a container for every tool, and
TES workers that can reach ``galaxy_url``. Not handled: reference data,
resubmission and job directory cleanup on the TES side.
"""

import logging
import os
from time import (
    monotonic,
    time,
)
from typing import (
    Any,
    TYPE_CHECKING,
)

from pulsar.client.tes_job_config import (
    parse_tes_job_params,
    tes_client_from_params,
)
from pydantictes.models import (
    TesResources,
    TesTask,
)

from galaxy import model
from galaxy.jobs.command_factory import build_command
from galaxy.jobs.runners import (
    AsynchronousJobRunner,
    AsynchronousJobState,
)
from galaxy.jobs.runners.util.tes_staging import (
    build_tes_task,
    directory_output_paths,
    job_directory_outputs,
    signed_job_files_url_for,
    staged_input_paths,
    wrapper_script,
)
from galaxy.jobs.runners.util.tes_task import (
    describe_ended_tes_task,
    describe_tes_error,
    fetch_tes_task_state,
    log_tes_cancel_failure,
    tes_known_secrets,
    tes_task_key,
    TES_TASK_NOT_FOUND,
    TesTaskKey,
)
from galaxy.util import asbool

if TYPE_CHECKING:
    from pulsar.client.tes_job_config import TesJobParams
    from pydantictes.api import TesClient

    from galaxy.app import GalaxyManagerApplication
    from galaxy.jobs import MinimalJobWrapper
    from galaxy.tool_util.deps.container_classes import Container

log = logging.getLogger(__name__)

__all__ = ("TesJobRunner",)

TES_RUNNER_PARAM_SPECS: dict[str, Any] = dict(
    galaxy_url=dict(map=str, default=None),
    tes_poll_interval=dict(map=float, valid=lambda x: float(x) > 0, default=10.0),
    # Cap on the life of each task URL's token; the job ending revokes them anyway.
    job_files_token_ttl=dict(map=int, valid=lambda x: int(x) > 0, default=7 * 24 * 3600),
)

# Written by the core job metrics plugin into the job directory.
CORE_METRICS_FILES = ("galaxy_slots", "galaxy_memory_mb", "epoch_start", "epoch_end")
TES_WAITING_STATES = frozenset(["UNKNOWN", "QUEUED", "INITIALIZING", "PAUSED", "CANCELING"])
TES_RUNNING_STATES = frozenset(["RUNNING"])


class TesJobRunner(AsynchronousJobRunner[AsynchronousJobState]):
    """Submit jobs as TES tasks that stage files over HTTP and run only the tool container; poll TES for state.

    Destination parameters are those of the Pulsar TES runner's destinations:
    ``tes_url``, ``authorization``/``basic_auth``, ``cpu_cores``, ``ram_gb``,
    ``disk_gb``, plus ``docker_enabled: true`` for container resolution and
    ``outputs_to_working_directory: true``. Runner parameters: ``galaxy_url`` (as
    task containers and the TES server see Galaxy; default
    ``galaxy_infrastructure_url``), ``tes_poll_interval`` (seconds between
    checks of each task, default 10) and ``job_files_token_ttl`` (seconds each
    task URL stays valid at most, default 7 days; URLs stop working when the job
    ends in any case).
    """

    runner_name = "TESRunner"
    # The job script doesn't set metadata in the task; Galaxy does, from the uploaded outputs.
    always_handle_metadata_externally = True

    def __init__(self, app: "GalaxyManagerApplication", nworkers: int, **kwds: Any) -> None:
        super().__init__(app, nworkers, runner_param_specs=TES_RUNNER_PARAM_SPECS, **kwds)
        self.galaxy_url: str = self.runner_params.galaxy_url or app.config.galaxy_infrastructure_url
        self.tes_poll_interval: float = self.runner_params.tes_poll_interval
        self.job_files_token_ttl: int = self.runner_params.job_files_token_ttl
        # Containers found while building command lines, by Galaxy job id, until the job is submitted.
        self._containers: dict[int, Container] = {}
        # Only the monitor thread touches this.
        self._next_checks: dict[TesTaskKey, float] = {}

    def build_command_line(
        self,
        job_wrapper: "MinimalJobWrapper",
        include_metadata: bool = False,
        include_work_dir_outputs: bool = True,
        modify_command_for_container: bool = True,
        stream_stdout_stderr: bool = False,
    ) -> str:
        container = self._find_container(job_wrapper)
        if not container:
            raise Exception("The TES runner runs every tool in a container, and none was found for this tool.")
        self._containers[job_wrapper.job_id] = container
        command: str = build_command(
            self,
            job_wrapper,
            include_metadata=include_metadata,
            include_work_dir_outputs=include_work_dir_outputs,
            modify_command_for_container=modify_command_for_container,
            container=container,
            stream_stdout_stderr=stream_stdout_stderr,
        )
        return command

    def queue_job(self, job_wrapper: "MinimalJobWrapper") -> None:
        job_state = AsynchronousJobState(
            job_wrapper=job_wrapper,
            job_destination=job_wrapper.job_destination,
            files_dir=job_wrapper.working_directory,
        )
        try:
            prepared = self.prepare_job(job_wrapper, include_metadata=False, modify_command_for_container=False)
            # Dropped however preparing ended: it can fail or finish the job after build_command_line.
            container = self._containers.pop(job_wrapper.job_id, None)
            if not prepared:
                return
            assert container
            job_script = self.get_job_file(
                job_wrapper, exit_code_path=job_state.exit_code_file, shell=job_wrapper.shell, galaxy_virtual_env=None
            )
            self.write_executable_script(job_state.job_file, job_script, job_io=job_wrapper.job_io)
            tes_params = parse_tes_job_params(job_wrapper.job_destination.params)
            task = self._build_task(job_wrapper, job_state, container, tes_params)
            task_id = tes_client_from_params(tes_params).create_task(task).id
        except Exception as e:
            log.exception("(%s) Failed to submit job as a TES task", job_wrapper.get_id_tag())
            job_wrapper.fail(f"Failed to submit job as a TES task: {describe_tes_error(e)}")
            return
        log.info(
            "(%s) Submitted as TES task %s: %d inputs, %d outputs, %d bytes of task JSON",
            job_wrapper.get_id_tag(),
            task_id,
            len(task.inputs or []),
            len(task.outputs or []),
            len(task.model_dump_json(exclude_none=True)),
        )
        job_state.job_id = task_id
        job_wrapper.set_external_id(task_id)
        self.monitor_job(job_state)

    def _build_task(
        self,
        job_wrapper: "MinimalJobWrapper",
        job_state: AsynchronousJobState,
        container: "Container",
        tes_params: "TesJobParams",
    ) -> TesTask:
        if not asbool(job_wrapper.get_destination_configuration("outputs_to_working_directory", False)):
            raise Exception("The TES runner needs outputs_to_working_directory: true on its destination.")
        job_directory = os.path.abspath(job_wrapper.working_directory)
        output_paths = self._output_paths(job_wrapper, job_state, job_directory)
        assert job_wrapper.tool
        input_paths = staged_input_paths(
            job_directory,
            job_wrapper.job_io.get_input_fnames(),
            job_wrapper.tool.tool_dir,
            exclude=output_paths,
        )
        directory_paths: list[str] = []
        if asbool(job_wrapper.get_destination_configuration("tes_directory_outputs", False)):
            directory_paths = directory_output_paths(
                job_directory,
                [str(path.false_extra_files_path) for path in job_wrapper.job_io.get_output_fnames()],
            )
        wrapper = wrapper_script(
            job_directory,
            job_state.job_file,
            job_state.exit_code_file,
            job_state.output_file,
            job_state.error_file,
            output_paths,
            precreated=[path for path in output_paths if os.path.exists(path)],
            directories=directory_paths,
        )
        return build_tes_task(
            name=f"galaxy-{job_wrapper.job_id}",
            image=container.container_id,
            job_directory=job_directory,
            input_paths=input_paths,
            output_paths=output_paths,
            wrapper=wrapper,
            url_for=signed_job_files_url_for(
                self.galaxy_url, self.app.security, job_wrapper.job_id, int(time()) + self.job_files_token_ttl
            ),
            resources=TesResources(
                cpu_cores=tes_params.cpu_cores, ram_gb=tes_params.ram_gb, disk_gb=tes_params.disk_gb
            ),
            directory_paths=directory_paths,
        )

    def _output_paths(
        self, job_wrapper: "MinimalJobWrapper", job_state: AsynchronousJobState, job_directory: str
    ) -> list[str]:
        """Files the task sends back: datasets, tool and job streams, exit code, core job metrics."""
        dataset_paths = [str(dataset_path.false_path) for dataset_path in job_wrapper.job_io.get_output_fnames()]
        outputs_directory = os.path.join(job_directory, "outputs")
        paths = [
            *dataset_paths,
            os.path.join(outputs_directory, "tool_stdout"),
            os.path.join(outputs_directory, "tool_stderr"),
            job_state.exit_code_file,
            job_state.output_file,
            job_state.error_file,
            *(os.path.join(job_directory, f"__instrument_core_{name}") for name in CORE_METRICS_FILES),
        ]
        return job_directory_outputs(job_directory, paths)

    def check_watched_item(self, job_state: AsynchronousJobState) -> AsynchronousJobState | None:
        task_key = tes_task_key(job_state)
        if job_state.check_limits():
            # fail_job cancels the task, since check_limits sets stop_job.
            self.work_queue.put((self.fail_job, job_state))
            keep_watching = False
        else:
            now = monotonic()
            if now < self._next_checks.get(task_key, 0):
                return job_state
            self._next_checks[task_key] = now + self.tes_poll_interval
            keep_watching = self._check_task(job_state, task_key[1])
        if keep_watching:
            return job_state
        self._next_checks.pop(task_key, None)
        return None

    def _check_task(self, job_state: AsynchronousJobState, task_id: str) -> bool:
        """Follow the job to the TES task's state: running, finished or failed. Return whether to keep watching."""
        if job_state.job_wrapper.get_state() not in (model.Job.states.QUEUED, model.Job.states.RUNNING):
            # Stopped, deleted or finished elsewhere.
            return False
        tes_params = parse_tes_job_params(job_state.job_destination.params)
        tes_client = tes_client_from_params(tes_params)
        try:
            task_state = fetch_tes_task_state(tes_client, task_id)
        except Exception as e:
            log.warning(
                "(%s/%s) Could not check TES task, will retry: %s",
                job_state.job_wrapper.get_id_tag(),
                task_id,
                describe_tes_error(e),
            )
            return True
        if task_state in TES_WAITING_STATES:
            return True
        if task_state in TES_RUNNING_STATES:
            if not job_state.running:
                job_state.running = True
                job_state.job_wrapper.change_state(model.Job.states.RUNNING)
            return True
        if task_state == "COMPLETE":
            log.debug("(%s/%s) TES task complete", job_state.job_wrapper.get_id_tag(), task_id)
            self.mark_as_finished(job_state)
            return False
        message, full_status = self._task_failure(tes_client, tes_params, task_id, task_state)
        # The task has ended, so there is nothing to cancel.
        job_state.stop_job = False
        self.fail_job(job_state, message=message, full_status=full_status)
        return False

    def _task_failure(
        self, tes_client: "TesClient", tes_params: "TesJobParams", task_id: str, task_state: str
    ) -> tuple[str, dict[str, Any] | None]:
        if task_state == TES_TASK_NOT_FOUND:
            return f"The TES server has no record of task {task_id}.", None
        task = None
        try:
            task = tes_client.get_task(task_id, "FULL")
        except Exception as e:
            log.warning("(%s) Could not read TES task logs: %s", task_id, describe_tes_error(e))
        # URL tokens in the logs are caught by redact()'s ``token=`` pattern.
        failure = describe_ended_tes_task(
            f"TES task {task_id} ended in state {task_state}.",
            task_state,
            task,
            secrets=tes_known_secrets(None, tes_params),
        )
        if failure.system_logs:
            log.info("(%s) %s\nTES system logs, last lines:\n%s", task_id, failure.message, failure.system_logs)
        return failure.message, {"stderr": failure.executor_stderr} if failure.executor_stderr else None

    def stop_job(self, job_wrapper: "MinimalJobWrapper") -> None:
        """Cancel the job's TES task. Never raises; a task that has already ended is left alone."""
        job = job_wrapper.get_job()
        task_id = job.job_runner_external_id
        if not task_id:
            return
        id_tag = job_wrapper.get_id_tag()
        destination_params = job.destination_params or {}
        try:
            tes_client_from_params(parse_tes_job_params(destination_params)).cancel_task(task_id)
        except Exception as e:
            log_tes_cancel_failure(log, destination_params, id_tag, task_id, describe_tes_error(e))
        else:
            log.info("(%s/%s) Cancelled TES task", id_tag, task_id)

    def recover(self, job: model.Job, job_wrapper: "MinimalJobWrapper") -> None:
        task_id = job.get_job_runner_external_id()
        if not task_id:
            job_wrapper.fail("The job's TES task id was lost, can't recover it.")
            return
        job_state = AsynchronousJobState(
            job_wrapper=job_wrapper,
            job_destination=job_wrapper.job_destination,
            files_dir=job_wrapper.working_directory,
            job_id=str(task_id),
        )
        job_state.running = job.state == model.Job.states.RUNNING
        log.debug("(%s/%s) Recovered TES job in state %s", job.id, task_id, job.state)
        self.monitor_job(job_state)
