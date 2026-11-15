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
import re
import shlex
from collections.abc import (
    Callable,
    Iterable,
)
from time import (
    monotonic,
    time,
)
from typing import (
    Any,
    TYPE_CHECKING,
)
from urllib.parse import urlencode

from pulsar.client.tes_job_config import (
    parse_tes_job_params,
    tes_client_from_params,
)
from pydantictes.models import (
    TesExecutor,
    TesFileType,
    TesInput,
    TesOutput,
    TesResources,
    TesTask,
)

from galaxy import model
from galaxy.jobs.command_factory import build_command
from galaxy.jobs.runners import (
    AsynchronousJobRunner,
    AsynchronousJobState,
)
from galaxy.jobs.runners.util.tes_task import (
    describe_ended_tes_task,
    describe_tes_error,
    fetch_tes_task_state,
    TES_NOTHING_TO_CANCEL_STATES,
    tes_task_key,
    TES_TASK_NOT_FOUND,
    TesTaskKey,
)
from galaxy.security.job_files_tokens import (
    JOB_FILES_DIRECTORY_WRITE,
    JOB_FILES_READ,
    job_files_token,
    JOB_FILES_WRITE,
    JobFilesScope,
)
from galaxy.util import (
    asbool,
    in_directory,
)

if TYPE_CHECKING:
    from pulsar.client.tes_job_config import TesJobParams
    from pydantictes.api import TesClient

    from galaxy.app import GalaxyManagerApplication
    from galaxy.jobs import MinimalJobWrapper
    from galaxy.security.idencoding import IdEncodingHelper
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
TES_WRAPPER_SCRIPT = "tes_job_wrapper.sh"
# Job directory files at most this large are searched for tool directory paths.
MAX_SCANNED_FILE_SIZE = 1024 * 1024
# Tool directories with at most this many files, test data excluded, are staged whole, so a
# tool script finds the modules and data next to it. Larger ones stage only referenced files.
MAX_TOOL_DIRECTORY_FILES = 200
TES_WAITING_STATES = frozenset(["UNKNOWN", "QUEUED", "INITIALIZING", "PAUSED", "CANCELING"])
TES_RUNNING_STATES = frozenset(["RUNNING"])
UrlFor = Callable[[str, JobFilesScope], str]
# Run by find with the job directory as $0 and symlinks as arguments: a link to a file
# in the job directory becomes a copy of it, any other link is removed.
REPLACE_LINKS = (
    'for l; do t=$(readlink -f "$l") || t=; case "$t" in "$0"/*) '
    'if [ -f "$t" ] && cp "$t" "$l.galaxy_copy" && mv -f "$l.galaxy_copy" "$l"; then continue; fi;; esac; '
    'rm -f "$l" "$l.galaxy_copy"; done'
)


def job_files_url(galaxy_url: str, encoded_job_id: str, path: str, job_token: str) -> str:
    """URL of ``path`` in Galaxy's job files API, authorized by ``job_token``."""
    query = urlencode({"path": path, "job_token": job_token})
    return f"{galaxy_url.rstrip('/')}/api/jobs/{encoded_job_id}/files?{query}"


def signed_job_files_url_for(galaxy_url: str, security: "IdEncodingHelper", job_id: int, expires: int) -> UrlFor:
    """A ``UrlFor`` whose URLs each carry a token for one path and one direction, valid until ``expires``."""
    encoded_job_id = security.encode_id(job_id)

    def url_for(path: str, scope: JobFilesScope) -> str:
        return job_files_url(galaxy_url, encoded_job_id, path, job_files_token(security, job_id, path, scope, expires))

    return url_for


def expand_paths(paths: Iterable[str]) -> list[str]:
    """Files at ``paths``, with directories walked into their files. Missing paths are skipped."""
    files: list[str] = []
    for path in paths:
        if os.path.isdir(path):
            for root, _, names in os.walk(path):
                files.extend(os.path.join(root, name) for name in sorted(names))
        elif os.path.isfile(path):
            files.append(path)
        else:
            log.debug("Not staging missing input path %s", path)
    return files


def directory_output_paths(job_directory: str, extra_files_paths: Iterable[str]) -> list[str]:
    """Directories the task sends back whole: the tool working directory and the outputs' extra files directories."""
    paths: dict[str, None] = {os.path.join(job_directory, "working"): None}
    for path in extra_files_paths:
        if not in_directory(path, job_directory):
            raise Exception(f"Job output {path} is outside the job directory, which the TES runner can't stage.")
        paths[os.path.abspath(path)] = None
    return list(paths)


def referenced_tool_files(tool_directory: str | None, texts: Iterable[str]) -> list[str]:
    """Files under ``tool_directory`` named in ``texts`` (job script, tool script, config files)."""
    if not tool_directory:
        return []
    tool_directory = os.path.abspath(tool_directory)
    pattern = re.compile(re.escape(tool_directory) + r"/[^\s'\"`<>|;&()]+")
    referenced = {match.rstrip(".,") for text in texts for match in pattern.findall(text)}
    return [path for path in expand_paths(sorted(referenced)) if in_directory(path, tool_directory)]


def tool_directory_files(tool_directory: str | None) -> list[str]:
    """Every file under ``tool_directory`` outside ``test-data`` and hidden directories, or none if there are too many."""
    if not tool_directory:
        return []
    files: list[str] = []
    for root, dirs, names in os.walk(tool_directory):
        dirs[:] = sorted(name for name in dirs if name != "test-data" and not name.startswith("."))
        files.extend(os.path.join(root, name) for name in sorted(names))
        if len(files) > MAX_TOOL_DIRECTORY_FILES:
            log.debug("Tool directory %s is too large to stage whole, staging the files the job names", tool_directory)
            return []
    return files


def staged_input_paths(
    job_directory: str,
    input_paths: Iterable[str],
    tool_directory: str | None,
    exclude: Iterable[str] = (),
) -> list[str]:
    """Every file the job may read, as absolute paths on Galaxy's disk, without duplicates."""
    excluded = {os.path.abspath(path) for path in exclude}
    job_files = [path for path in expand_paths([job_directory]) if os.path.abspath(path) not in excluded]
    texts = []
    for path in job_files:
        if os.path.getsize(path) <= MAX_SCANNED_FILE_SIZE:
            with open(path, errors="replace") as fh:
                texts.append(fh.read())
    staged: dict[str, None] = {}
    tool_files = [*referenced_tool_files(tool_directory, texts), *tool_directory_files(tool_directory)]
    for path in [*expand_paths(input_paths), *job_files, *tool_files]:
        staged[os.path.abspath(path)] = None
    return list(staged)


def wrapper_script(
    job_directory: str,
    job_script: str,
    exit_code_file: str,
    stdout_file: str,
    stderr_file: str,
    outputs: Iterable[str],
    precreated: Iterable[str] = (),
    directories: Iterable[str] = (),
) -> str:
    """The executor's script: run Galaxy's job script, keep its exit code in a file, exit 0.

    ``precreated`` are the empty output files Galaxy created on its disk while
    preparing the job; they are created in the task too, because the job script's
    ``from_work_dir`` copies only write to outputs that exist.

    TESK and tesp-api skip stage-out after a failed executor, so the script always
    exits 0 and Galaxy reads the tool's exit code from the uploaded file. Funnel and
    TESK fail a task whose FILE output is missing, so every declared output is
    created, empty, after the job script if the job didn't write it.

    ``directories`` (TES ``DIRECTORY`` outputs) are created before the job script
    and lose their symlinks after it: TESK refuses a directory output with any
    symlink in it, and Funnel one whose links leave the task. A link to a file
    in the job directory is replaced by a copy of that file, so its contents
    still go back; any other link is removed.
    """
    q = shlex.quote
    directories = list(directories)
    lines = [
        "#!/bin/sh",
        "# Written by Galaxy's TES runner. Runs Galaxy's job script, then always exits 0.",
        f"cd {q(job_directory)} || exit 0",
        # TES creates no empty directories; the job script creates working, outputs and configs itself.
        "mkdir -p home tmp metadata",
        *([f"mkdir -p {' '.join(q(d) for d in directories)}"] if directories else []),
        *_touch_loop(precreated),
        f"/bin/bash {q(job_script)} > {q(stdout_file)} 2> {q(stderr_file)}",
        "rc=$?",
        f"[ -s {q(exit_code_file)} ] || echo $rc > {q(exit_code_file)}",
        *_touch_loop(outputs),
        *(
            [
                f"find {' '.join(q(d) for d in directories)} -type l -exec sh -c {q(REPLACE_LINKS)} {q(job_directory)} {{}} +"
            ]
            if directories
            else []
        ),
        "exit 0",
        "",
    ]
    return "\n".join(lines)


def _touch_loop(paths: Iterable[str]) -> list[str]:
    """Shell lines that create each of ``paths`` as an empty file unless it exists."""
    quoted = [shlex.quote(path) for path in paths]
    if not quoted:
        return []
    return [
        "for f in \\",
        *(f"    {path} \\" for path in quoted),
        "    ; do",
        '    [ -e "$f" ] || { mkdir -p "$(dirname "$f")" && : > "$f"; }',
        "done",
    ]


def build_tes_task(
    name: str,
    image: str,
    job_directory: str,
    input_paths: Iterable[str],
    output_paths: Iterable[str],
    wrapper: str,
    url_for: UrlFor,
    resources: TesResources | None = None,
    env: dict[str, str] | None = None,
    directory_paths: Iterable[str] = (),
) -> TesTask:
    """A TES task that stages ``input_paths`` in, runs ``wrapper`` in ``image`` and stages ``output_paths`` out.

    Every path is the same inside the task as on Galaxy's disk.
    """
    wrapper_path = os.path.join(job_directory, TES_WRAPPER_SCRIPT)
    inputs = [TesInput(url=url_for(path, JOB_FILES_READ), path=path, type=TesFileType.FILE) for path in input_paths]
    inputs.append(TesInput(content=wrapper, path=wrapper_path, type=TesFileType.FILE))
    outputs = [TesOutput(url=url_for(path, JOB_FILES_WRITE), path=path, type=TesFileType.FILE) for path in output_paths]
    outputs.extend(
        TesOutput(url=url_for(path, JOB_FILES_DIRECTORY_WRITE), path=path, type=TesFileType.DIRECTORY)
        for path in directory_paths
    )
    executor = TesExecutor(image=image, command=["/bin/sh", wrapper_path], workdir=job_directory, env=env or None)
    return TesTask(
        name=name,
        inputs=inputs,
        outputs=outputs,
        executors=[executor],
        # Shared by the executor and stage-out, writable; inputs land inside it.
        volumes=[job_directory],
        resources=resources,
    )


def executor_env(resources: TesResources) -> dict[str, str]:
    """``GALAXY_SLOTS`` and ``GALAXY_MEMORY_MB`` for the job script, from the TES resources."""
    env = {}
    if resources.cpu_cores:
        env["GALAXY_SLOTS"] = str(resources.cpu_cores)
    if resources.ram_gb:
        env["GALAXY_MEMORY_MB"] = str(int(resources.ram_gb * 1024))
    return env


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
            if not self.prepare_job(job_wrapper, include_metadata=False, modify_command_for_container=False):
                return
            container = self._containers.pop(job_wrapper.job_id)
            job_script = self.get_job_file(
                job_wrapper, exit_code_path=job_state.exit_code_file, shell=job_wrapper.shell, galaxy_virtual_env=None
            )
            self.write_executable_script(job_state.job_file, job_script, job_io=job_wrapper.job_io)
            tes_params = parse_tes_job_params(job_wrapper.job_destination.params)
            task = self._build_task(job_wrapper, job_state, container, tes_params)
            task_id = tes_client_from_params(tes_params).create_task(task).id
        except Exception as e:
            self._containers.pop(job_wrapper.job_id, None)
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
        resources = TesResources(cpu_cores=tes_params.cpu_cores, ram_gb=tes_params.ram_gb, disk_gb=tes_params.disk_gb)
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
            resources=resources,
            env=executor_env(resources),
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
        for path in paths:
            if not in_directory(path, job_directory):
                raise Exception(f"Job output {path} is outside the job directory, which the TES runner can't stage.")
        return [os.path.abspath(path) for path in paths]

    def check_watched_item(self, job_state: AsynchronousJobState) -> AsynchronousJobState | None:
        task_key = tes_task_key(job_state)
        task_id = task_key[1]
        if job_state.check_limits():
            # fail_job cancels the task, since check_limits sets stop_job.
            self._next_checks.pop(task_key, None)
            self.work_queue.put((self.fail_job, job_state))
            return None
        now = monotonic()
        if now < self._next_checks.get(task_key, 0):
            return job_state
        self._next_checks[task_key] = now + self.tes_poll_interval
        if job_state.job_wrapper.get_state() not in (model.Job.states.QUEUED, model.Job.states.RUNNING):
            # Stopped, deleted or finished elsewhere.
            self._next_checks.pop(task_key, None)
            return None
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
            return job_state
        if task_state in TES_WAITING_STATES:
            return job_state
        if task_state in TES_RUNNING_STATES:
            if not job_state.running:
                job_state.running = True
                job_state.job_wrapper.change_state(model.Job.states.RUNNING)
            return job_state
        self._next_checks.pop(task_key, None)
        if task_state == "COMPLETE":
            log.debug("(%s/%s) TES task complete", job_state.job_wrapper.get_id_tag(), task_id)
            self.mark_as_finished(job_state)
            return None
        message, full_status = self._task_failure(tes_client, tes_params, job_state, task_state)
        # The task has ended, so there is nothing to cancel.
        job_state.stop_job = False
        self.fail_job(job_state, message=message, full_status=full_status)
        return None

    def _task_failure(
        self, tes_client: "TesClient", tes_params: "TesJobParams", job_state: AsynchronousJobState, task_state: str
    ) -> tuple[str, dict[str, Any] | None]:
        task_id = job_state.job_id
        if task_state == TES_TASK_NOT_FOUND:
            return f"The TES server has no record of task {task_id}.", None
        message = f"TES task {task_id} ended in state {task_state}."
        # URL tokens in the logs are caught by redact()'s ``token=`` pattern.
        secrets = []
        if tes_params.basic_auth:
            secrets.append(tes_params.basic_auth.password)
        try:
            failure = describe_ended_tes_task(
                message, task_state, tes_client.get_task(task_id, "FULL"), secrets=secrets
            )
        except Exception as e:
            log.warning("(%s) Could not read TES task logs: %s", task_id, describe_tes_error(e))
            return message, None
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
        tes_client = tes_client_from_params(parse_tes_job_params(job.destination_params))
        try:
            tes_client.cancel_task(task_id)
            log.info("(%s/%s) Cancelled TES task", id_tag, task_id)
            return
        except Exception as e:
            cancel_error = describe_tes_error(e)
        # TESK answers 400 to cancelling a task that has ended, and servers answer 404 for a deleted one.
        try:
            task_state = fetch_tes_task_state(tes_client, task_id)
        except Exception as e:
            log.error(
                "(%s/%s) Failed to cancel TES task and could not read its state, so it may still be running. "
                "Cancel error: %s. State error: %s",
                id_tag,
                task_id,
                cancel_error,
                describe_tes_error(e),
            )
            return
        if task_state in TES_NOTHING_TO_CANCEL_STATES:
            log.info("(%s/%s) TES task is %s, nothing to cancel", id_tag, task_id, task_state)
        else:
            log.error(
                "(%s/%s) Failed to cancel TES task in state %s, it may still be running: %s",
                id_tag,
                task_id,
                task_state,
                cancel_error,
            )

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
