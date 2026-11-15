"""PulsarTesJobRunner fails jobs whose TES task dies before Pulsar reports.

The runner talks to a fake TES server over HTTP through pydantic-tes, the
client Pulsar uses to submit the tasks.
"""

import copy
import json
import logging
import threading
from dataclasses import (
    dataclass,
    field,
)
from http.server import (
    BaseHTTPRequestHandler,
    ThreadingHTTPServer,
)
from queue import Queue
from typing import (
    Any,
    cast,
)
from unittest.mock import Mock
from urllib.parse import (
    parse_qs,
    urlparse,
)

import pytest

from galaxy import model
from galaxy.jobs import MinimalJobWrapper
from galaxy.jobs.job_destination import JobDestination
from galaxy.jobs.runners import (
    AsynchronousJobState,
    pulsar as pulsar_runner,
)
from galaxy.jobs.runners.pulsar import (
    PulsarMQJobRunner,
    PulsarTesJobRunner,
)
from galaxy.jobs.runners.util.tes_task import redact

TASK_ID = "d4rk5c3bf5d1q0abcdef"
GALAXY_JOB_ID = 42
# The runner's defaults, which the harness relies on.
INTERVAL = 60.0
GRACE = 120.0
SERVER_NAME = "main.handler0"
AMQP_PASSWORD = "Br0kerPassword"
STAGING_IMAGE = "galaxy/pulsar-pod-staging:0.15.0.2"
# Job.info is cut at this length, so failure messages must fit.
# TrimmedString passes the length through from its String implementation.
JOB_INFO_LENGTH: int = model.Job.__table__.c.info.type.length  # type: ignore[attr-defined]
# Stand-ins for the base64 job description and app configuration Pulsar passes
# its executors; the real ones carry the message queue credentials.
JOB_BASE64 = "eyJqb2JfaWQiOiAiNDIiLCAibWVzc2FnZV9xdWV1ZV91cmwiOiAiYW1xcDovL2d1ZXN0OnMzY3IzdEBicm9rZXIifQ=="
APP_CONF_BASE64 = "eyJtZXNzYWdlX3F1ZXVlX3VybCI6ICJhbXFwOi8vZ3Vlc3Q6czNjcjN0QGJyb2tlciJ9"


def _executors():
    return [
        {
            "image": STAGING_IMAGE,
            "command": ["pulsar-submit", "--base64", JOB_BASE64, "--app_conf_base64", APP_CONF_BASE64],
        },
        {"image": "quay.io/biocontainers/samtools:1.21", "command": ["bash", "/pulsar_staging/42/tool_script.sh"]},
        {
            "image": STAGING_IMAGE,
            "command": ["pulsar-finish", "--base64", JOB_BASE64, "--app_conf_base64", APP_CONF_BASE64],
        },
    ]


def _task(state, executor_logs=None, system_logs=None, executors=None):
    task: dict[str, Any] = {"id": TASK_ID, "state": state, "name": "pulsar-42", "executors": executors or _executors()}
    if executor_logs is not None:
        task["logs"] = [{"logs": executor_logs, "system_logs": system_logs or []}]
    return task


RUNNING_COMMAND = (
    f"docker run -i {STAGING_IMAGE} pulsar-submit --base64 {JOB_BASE64} --app_conf_base64 {APP_CONF_BASE64}"
)
RUNNING_COMMAND_LOG = f"level='info' msg='Running command' cmd='{RUNNING_COMMAND}'"
STAGING_FAILURE_STDERR = "\n".join(
    [f"noise line {i}" for i in range(40)]
    + [
        f"pulsar-submit --base64 {JOB_BASE64}",
        "Traceback (most recent call last):",
        '  File "/usr/local/lib/python3.12/site-packages/galaxy/tool_util/deps/installable.py", line 63, in ensure_installed',
        "    os.mkdir(parent_path)",
        "OSError: [Errno 30] Read-only file system: '/dependencies'",
    ]
)


# TESK's answer to cancelling a task that has already ended.
TESK_CANCEL_ENDED_TASK_STATUS = 400
TESK_CANCEL_ENDED_TASK_BODY = {
    "title": "Bad Request",
    "status": 400,
    "detail": f"Job with ID={TASK_ID} has no pods in RUNNING status.",
}


class FakeTesServer:
    """Serves ``GET /v1/tasks/{id}`` the way Funnel does: BASIC drops stdout, stderr and system logs.

    ``POST /v1/tasks/{id}:cancel`` answers ``cancel_status`` with ``cancel_body`` for known tasks.
    """

    def __init__(self):
        self.tasks: dict[str, dict[str, Any]] = {}
        self.requests: list[tuple[str, str]] = []
        self.error_status: int | None = None
        self.cancel_status = 200
        self.cancel_body: dict[str, Any] = {}
        server = self

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                url = urlparse(self.path)
                task_id = url.path.rsplit("/", 1)[-1]
                view = parse_qs(url.query).get("view", ["MINIMAL"])[0]
                server.requests.append((task_id, view))
                if server.error_status:
                    self._send(server.error_status, {"error": "backend unavailable"})
                elif task_id not in server.tasks:
                    self._send(404, {"error": f"task not found: taskID: {task_id}"})
                else:
                    self._send(200, server.view(server.tasks[task_id], view))

            def do_POST(self):
                task_id = urlparse(self.path).path.rsplit("/", 1)[-1].removesuffix(":cancel")
                server.requests.append((task_id, "POST"))
                if task_id not in server.tasks:
                    self._send(404, {"error": f"task not found: taskID: {task_id}"})
                else:
                    self._send(server.cancel_status, server.cancel_body)

            def _send(self, status, body):
                payload = json.dumps(body).encode()
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)

            def log_message(self, format, *args):
                pass

        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.url = f"http://127.0.0.1:{self.httpd.server_address[1]}/"
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)
        self.thread.start()

    @staticmethod
    def view(task, view):
        task = copy.deepcopy(task)
        if view != "FULL":
            for attempt in task.get("logs", []):
                attempt.pop("system_logs", None)
                for executor_log in attempt["logs"]:
                    executor_log.pop("stdout", None)
                    executor_log.pop("stderr", None)
        return task

    def views_requested(self):
        return [view for _, view in self.requests]

    def stop(self):
        self.httpd.shutdown()
        self.httpd.server_close()


@pytest.fixture
def tes_server():
    server = FakeTesServer()
    yield server
    server.stop()


class Clock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now


@pytest.fixture
def clock(monkeypatch):
    clock = Clock()
    monkeypatch.setattr(pulsar_runner, "monotonic", clock, raising=False)
    return clock


@dataclass
class FakeJob:
    id: int = GALAXY_JOB_ID
    state: str = model.Job.states.QUEUED
    job_runner_external_id: str = TASK_ID
    job_runner_name: str = "pulsar_tes://"
    handler: str = SERVER_NAME
    destination_params: dict[str, Any] = field(default_factory=dict)

    def get_job_runner_external_id(self):
        return self.job_runner_external_id

    def get_external_output_metadata(self):
        return []


@dataclass
class FakeTool:
    old_id: str = "cat1"


class FakeJobWrapper:
    """Just what ``AsynchronousJobState`` and ``fail_job`` use; records failures.

    Set ``state_error`` to make reading the job's state raise, as a lost database connection does.
    """

    def __init__(self, app):
        self.app = app
        self.job = FakeJob()
        self.job_id = GALAXY_JOB_ID
        self.tool = FakeTool()
        self.user = None
        self.guest_ports: list[int] = []
        self.failures: list[dict[str, Any]] = []
        self.state_error: Exception | None = None
        # Each read is a database query in the real job wrapper.
        self.state_reads = 0

    def get_id_tag(self):
        return str(self.job_id)

    def get_state(self):
        self.state_reads += 1
        if self.state_error:
            raise self.state_error
        return self.job.state

    def get_job(self):
        return self.job

    def reclaim_ownership(self):
        pass

    def fail(self, message, exception=False, tool_stdout="", tool_stderr="", **kwds):
        self.failures.append({"message": message, "tool_stderr": tool_stderr})
        self.job.state = model.Job.states.ERROR


class Harness:
    """A TES runner watching one job."""

    def __init__(self, tes_server, clock):
        self.tes_server = tes_server
        self.clock = clock
        self.runner = _runner(PulsarTesJobRunner, amqp_url=f"amqp://galaxy:{AMQP_PASSWORD}@broker:5672//")
        self.runner.work_queue = Queue()
        self.runner._init_client_manager()
        self.job_wrapper = FakeJobWrapper(self.runner.app)
        self.job = self.job_wrapper.job
        self.job.destination_params = self.destination_params()
        self.job_state = self.job_state_for(self.job_wrapper)

    def destination_params(self, tes_url=None):
        return {"tes_url": tes_url or self.tes_server.url, "pulsar_container_image": STAGING_IMAGE}

    def job_state_for(self, job_wrapper, tes_url=None):
        destination = JobDestination(params=self.destination_params(tes_url))
        return AsynchronousJobState(
            job_wrapper=cast(MinimalJobWrapper, job_wrapper), job_destination=destination, job_id=TASK_ID
        )

    @property
    def failures(self):
        return self.job_wrapper.failures

    def check(self):
        return self.runner.check_watched_item(self.job_state)

    def check_after(self, seconds):
        self.clock.now += seconds
        return self.check()

    def watch_for(self, seconds):
        """Check every monitor loop iteration (one second) for this long; return whether still watched."""
        for _ in range(int(seconds)):
            if self.check_after(1) is None:
                return False
        return True


@pytest.fixture
def harness(tes_server, clock):
    return Harness(tes_server, clock)


@pytest.fixture
def other_tes_server():
    server = FakeTesServer()
    yield server
    server.stop()


def test_task_dying_before_pulsar_reports_fails_the_job(harness, tes_server, caplog):
    caplog.set_level(logging.INFO, logger=pulsar_runner.__name__)
    tes_server.tasks[TASK_ID] = _task(
        "EXECUTOR_ERROR",
        executor_logs=[{"exit_code": 1, "stdout": "", "stderr": STAGING_FAILURE_STDERR}],
        system_logs=[
            RUNNING_COMMAND_LOG,
            "level='error' msg='Exec failed' error='exit status 1'",
        ],
    )

    assert harness.check() is harness.job_state
    assert tes_server.requests == [], "the first TES check waits one interval"
    # Detected on the first check, then given the grace period to report.
    assert harness.watch_for(INTERVAL + GRACE - 1)
    assert harness.failures == []
    assert not harness.watch_for(INTERVAL)

    assert tes_server.views_requested() == ["BASIC", "BASIC", "BASIC", "FULL"]
    [failure] = harness.failures
    # Funnel logs only the executors that ran, so this is executor 0's log, but tesp-api
    # stores one log like it for the whole task, so it isn't attributed.
    assert failure["message"] == (
        f"TES task {TASK_ID} ended in state EXECUTOR_ERROR before Pulsar reported a final job status. "
        "The task exited with code 1."
    )
    assert len(failure["message"]) <= JOB_INFO_LENGTH
    details = failure["tool_stderr"]
    assert details.startswith("Task stderr, last lines:")
    assert "OSError: [Errno 30] Read-only file system: '/dependencies'" in details
    assert "galaxy/tool_util/deps/installable.py" in details
    assert "noise line 19" not in details
    assert "pulsar-submit --base64 [redacted]" in details
    assert "Exec failed" not in details
    # System logs describe the TES hosts; they go to admins only, redacted like stderr.
    [log_message] = [record.getMessage() for record in caplog.records if "TES system logs" in record.getMessage()]
    assert failure["message"] in log_message
    assert "level='error' msg='Exec failed' error='exit status 1'" in log_message
    assert "pulsar-submit --base64 [redacted] --app_conf_base64 [redacted]" in log_message
    for text in (details, *(record.getMessage() for record in caplog.records)):
        assert JOB_BASE64[:32] not in text
        assert APP_CONF_BASE64[:32] not in text


@pytest.mark.parametrize(
    "state",
    # Pulsar's final status was processed, or the job was stopped or deleted.
    [model.Job.states.ERROR, model.Job.states.OK, model.Job.states.DELETING, model.Job.states.STOPPED],
)
def test_jobs_no_longer_queued_or_running_stop_the_checks(harness, tes_server, state):
    tes_server.tasks[TASK_ID] = _task("EXECUTOR_ERROR", executor_logs=[{"exit_code": 1}])
    harness.check()
    harness.check_after(INTERVAL)
    harness.job.state = state

    assert harness.check_after(INTERVAL) is None
    assert tes_server.views_requested() == ["BASIC"]
    assert harness.failures == []


def test_running_task_is_checked_once_per_interval_and_left_alone(harness, tes_server):
    tes_server.tasks[TASK_ID] = _task("RUNNING", executor_logs=[{"exit_code": 0}])
    harness.check()
    # The monitor loop runs every second; only checks that are due read the job or ask the TES server.
    assert harness.watch_for(10 * INTERVAL)
    assert tes_server.views_requested() == ["BASIC"] * 10
    assert harness.job_wrapper.state_reads == 10
    assert harness.failures == []


def test_completed_task_without_a_final_status_fails_the_job(harness, tes_server):
    tes_server.tasks[TASK_ID] = _task(
        "COMPLETE",
        executor_logs=[
            {"exit_code": 0, "stderr": "staged"},
            {"exit_code": 0, "stderr": "tool ran"},
            {"exit_code": 0, "stderr": "Failed to publish status: [Errno 111] Connection refused"},
        ],
    )
    harness.check()
    assert not harness.watch_for(INTERVAL + GRACE + INTERVAL)

    [failure] = harness.failures
    assert failure["message"] == (
        f"TES task {TASK_ID} completed, but Pulsar never reported a final job status. "
        "Executor 2 (pulsar-finish) ran last and exited with code 0."
    )
    assert len(failure["message"]) <= JOB_INFO_LENGTH
    assert f"Executor 2 (pulsar-finish, image {STAGING_IMAGE}) stderr, last lines:" in failure["tool_stderr"]
    assert "Failed to publish status: [Errno 111] Connection refused" in failure["tool_stderr"]


def test_failure_message_fits_job_info_with_long_image_names(harness, tes_server):
    long_image = (
        "quay.io/biocontainers/mulled-v2-8374e50c663bfd36021a9219b02d97e9c4baaad5:"
        "783e4c36591c28e0c25d1c1084e0a4a5ca32fd17-0"
    )
    executors = _executors()
    executors[1]["image"] = long_image
    tes_server.tasks[TASK_ID] = _task(
        "EXECUTOR_ERROR",
        executors=executors,
        executor_logs=[{"exit_code": 0}, {"exit_code": 137, "stderr": "Killed"}],
    )
    harness.check()
    assert not harness.watch_for(INTERVAL + GRACE + INTERVAL)

    [failure] = harness.failures
    assert failure["message"].endswith("Executor 1 exited with code 137.")
    assert len(failure["message"]) <= JOB_INFO_LENGTH
    assert f"Executor 1 (image {long_image}) stderr, last lines:\nKilled" in failure["tool_stderr"]


@pytest.mark.parametrize(
    "state, exit_code, summary",
    [
        ("EXECUTOR_ERROR", 125, "The task exited with code 125."),
        ("COMPLETE", 0, "The task exited with code 0."),
        ("SYSTEM_ERROR", None, "The task reported no exit code."),
    ],
)
def test_one_log_for_all_executors_is_not_attributed_to_one(harness, tes_server, state, exit_code, summary):
    # tesp-api runs a task's executors as one Pulsar job and stores one log for them.
    executor_log: dict[str, Any] = {"stderr": "+ docker run ...\nUnable to find image"}
    if exit_code is not None:
        executor_log["exit_code"] = exit_code
    tes_server.tasks[TASK_ID] = _task(state, executor_logs=[executor_log])
    harness.check()
    assert not harness.watch_for(INTERVAL + GRACE + INTERVAL)

    [failure] = harness.failures
    assert failure["message"].endswith(f"final job status. {summary}")
    assert "Executor" not in failure["message"]
    assert "pulsar-submit" not in failure["message"]
    assert failure["tool_stderr"] == "Task stderr, last lines:\n+ docker run ...\nUnable to find image"


# Funnel 0.12.3 SYSTEM_ERROR system logs, from the stage 6 argv runs (runs/stage6/argv/tes-level/funnel/galaxy.json
# and runs/tesp-probes/design-b/evidence/results/t8-*.json in the demo repository), with paths, ids and the long
# docker command shortened. Funnel records exit code 0 for an executor it could not start.
FUNNEL_ARGV_SYSTEM_LOGS = [
    (
        "level='info' msg='Version' timestamp='2026-11-15T02:11:05.929931193Z' task_attempt='0' executor_index='0' "
        "Version='0.12.3' GitCommit='738ab75a' GitBranch='v0.12.3' GitUpstream='https://github.com/calypr/funnel'"
    ),
    (
        "level='error' msg='failed to pull docker image using command' timestamp='2026-11-15T02:11:06.596165975Z' "
        "task_attempt='0' executor_index='0' exit_status_1='pull {{.Image}}'"
    ),
    (
        "level='info' msg='Running command' timestamp='2026-11-15T02:11:06.612017584Z' task_attempt='0' executor_index='0' "
        f"cmd='/usr/bin/docker run -i --rm --name {TASK_ID}-0 --workdir / --volume /work/{TASK_ID}/pulsar_staging:"
        f"/pulsar_staging:rw {STAGING_IMAGE} pulsar-submit --no-wait --base64 {JOB_BASE64} --app_conf_base64 {APP_CONF_BASE64}'"
    ),
    (
        "level='error' msg='failed to run docker container' timestamp='2026-11-15T02:11:06.624469219Z' task_attempt='0' "
        "executor_index='0' unknown='fork/exec /usr/bin/docker: argument list too long'"
    ),
    (
        "level='error' msg='failed to get exit code: fork/exec /usr/bin/docker: argument list too long' "
        "timestamp='2026-11-15T02:11:06.648944403Z' task_attempt='0' executor_index='0'"
    ),
    (
        "level='error' msg='System error' timestamp='2026-11-15T02:11:06.669537216Z' task_attempt='0' executor_index='0' "
        "error='fork/exec /usr/bin/docker: argument list too long'"
    ),
]
FUNNEL_DOWNLOAD_SYSTEM_LOGS = [
    (
        "level='info' msg='download started' timestamp='2026-11-14T21:28:20.928273819Z' task_attempt='0' "
        "executor_index='0' url='http://172.17.0.1:18301/data/does-not-exist.txt'"
    ),
    (
        "level='error' msg='download failed' timestamp='2026-11-14T21:28:20.936770544Z' task_attempt='0' "
        "executor_index='0' error='httpStorage: GET request returned status code: 404' "
        "url='http://172.17.0.1:18301/data/does-not-exist.txt'"
    ),
    (
        "level='error' msg='System error' timestamp='2026-11-14T21:28:20.954311183Z' task_attempt='0' "
        "executor_index='0' error='httpStorage: GET request returned status code: 404'"
    ),
]
# tesp-api with patch 0011 (stage_failure_log): one entry, the reason, then the tail of the job's stderr.
TESP_STAGE_IN_SYSTEM_LOGS = [
    (
        "stage-in failed (exit code 22): downloading the inputs failed\n"
        "  % Total    % Received % Xferd  Average Speed   Time    Time     Time  Current\n"
        "curl: (22) The requested URL returned error: 404"
    )
]
TESP_SUBMISSION_SYSTEM_LOGS = [
    (
        "the job did not start: Pulsar or the batch system refused it (for example, resources the batch system cannot "
        "provide); Pulsar's log has the details"
    )
]
# TESK: the whole taskmaster pod log as one entry, in tesk-core 0.11.0's format ("%(asctime)s %(levelname)s:
# %(message)s"); a job that doesn't complete ends the taskmaster through exit_cancelled.
TESK_SYSTEM_LOGS = [
    (
        "2026-11-14 18:42:10 INFO: Keeping PVC 'task-1a2b3c4d-pvc' (TESK_KEEP_FAILED_PVC)\n"
        "2026-11-14 18:42:20 ERROR: Cancelling taskmaster: Got status Failed\n"
    )
]


@pytest.mark.parametrize(
    "executor_logs, system_logs, summary",
    [
        # Funnel couldn't start executor 0 and still logs exit code 0 for it.
        (
            [{"exit_code": 0, "stdout": "", "stderr": ""}],
            FUNNEL_ARGV_SYSTEM_LOGS,
            "System log: fork/exec /usr/bin/docker: argument list too long",
        ),
        # Funnel's input download failed before any executor ran.
        ([], FUNNEL_DOWNLOAD_SYSTEM_LOGS, "System log: httpStorage: GET request returned status code: 404"),
        (
            [],
            TESP_STAGE_IN_SYSTEM_LOGS,
            (
                "System log: stage-in failed (exit code 22): downloading the inputs failed: "
                "curl: (22) The requested URL returned error: 404"
            ),
        ),
        ([], TESK_SYSTEM_LOGS, "System log: Cancelling taskmaster: Got status Failed"),
    ],
    ids=["funnel-argv", "funnel-download", "tesp-api-stage-in", "tesk"],
)
def test_system_error_names_the_system_log_reason(harness, tes_server, executor_logs, system_logs, summary):
    tes_server.tasks[TASK_ID] = _task("SYSTEM_ERROR", executor_logs=executor_logs, system_logs=system_logs)
    harness.check()
    assert not harness.watch_for(INTERVAL + GRACE + INTERVAL)

    [failure] = harness.failures
    assert failure["message"] == (
        f"TES task {TASK_ID} ended in state SYSTEM_ERROR before Pulsar reported a final job status. {summary}"
    )
    assert "exit code 0" not in failure["message"]
    assert "exited with code" not in failure["message"]
    assert len(failure["message"]) <= JOB_INFO_LENGTH


def test_system_error_reason_is_cut_to_fit_job_info(harness, tes_server):
    long_task_id = "d08e39e6-e099-11f1-ad59-fa163e1c6750"
    harness.job.job_runner_external_id = long_task_id
    harness.job_state.job_id = long_task_id
    tes_server.tasks[long_task_id] = dict(
        _task("SYSTEM_ERROR", executor_logs=[], system_logs=TESP_SUBMISSION_SYSTEM_LOGS), id=long_task_id
    )
    harness.check()
    assert not harness.watch_for(INTERVAL + GRACE + INTERVAL)

    [failure] = harness.failures
    assert "System log: the job did not start: Pulsar or the batch system refused it" in failure["message"]
    assert failure["message"].endswith("...")
    assert len(failure["message"]) <= JOB_INFO_LENGTH


def test_system_error_keeps_a_failing_executors_exit_code_and_redacts_the_reason(harness, tes_server):
    tes_server.tasks[TASK_ID] = _task(
        "SYSTEM_ERROR",
        executor_logs=[{"exit_code": 0}, {"exit_code": 2, "stderr": "tool failed"}],
        system_logs=[
            "level='error' msg='System error' error='upload to amqp://galaxy:"
            + AMQP_PASSWORD
            + "@broker:5672// failed: "
            + "x" * 300
            + "'"
        ],
    )
    harness.check()
    assert not harness.watch_for(INTERVAL + GRACE + INTERVAL)

    [failure] = harness.failures
    assert "final job status. Executor 1 exited with code 2. System log: upload to amqp://[redacted]@broker" in (
        failure["message"]
    )
    assert AMQP_PASSWORD not in failure["message"]
    assert len(failure["message"]) <= JOB_INFO_LENGTH


def test_system_error_without_a_reason_claims_no_exit_code(harness, tes_server):
    tes_server.tasks[TASK_ID] = _task("SYSTEM_ERROR", executor_logs=[{"exit_code": 0}])
    harness.check()
    assert not harness.watch_for(INTERVAL + GRACE + INTERVAL)

    [failure] = harness.failures
    assert failure["message"].endswith("final job status. No executor reported a failure.")


def test_logs_of_the_executors_that_ran_are_attributed_to_them(harness, tes_server):
    # Funnel, TESK and tesp-api with per-executor logs record the executors that ran, up to the failing one.
    tes_server.tasks[TASK_ID] = _task(
        "EXECUTOR_ERROR", executor_logs=[{"exit_code": 0}, {"exit_code": 2, "stderr": "tool failed"}]
    )
    harness.check()
    assert not harness.watch_for(INTERVAL + GRACE + INTERVAL)

    [failure] = harness.failures
    assert failure["message"].endswith("final job status. Executor 1 exited with code 2.")
    assert failure["tool_stderr"].startswith("Executor 1 (image quay.io/biocontainers/samtools:1.21) stderr")


def test_task_unknown_to_the_tes_server_fails_the_job(harness, tes_server):
    harness.check()
    assert not harness.watch_for(INTERVAL + GRACE + INTERVAL)

    # A lost task can't be cancelled; trying would raise before the job fails.
    assert tes_server.views_requested() == ["BASIC", "BASIC", "BASIC"]
    [failure] = harness.failures
    assert failure == {
        "message": f"The TES server has no record of task {TASK_ID}, and Pulsar never reported a final job status.",
        "tool_stderr": None,
    }


def test_tes_states_newer_than_pydantic_tes_are_recognized(harness, tes_server):
    tes_server.tasks[TASK_ID] = _task("PREEMPTED", executor_logs=[{"exit_code": 0}])
    harness.check()
    assert not harness.watch_for(INTERVAL + GRACE + INTERVAL)

    [failure] = harness.failures
    # The FULL view doesn't parse either, so there is nothing to add.
    assert failure == {
        "message": f"TES task {TASK_ID} ended in state PREEMPTED before Pulsar reported a final job status.",
        "tool_stderr": None,
    }


def test_task_back_to_running_restarts_the_grace_period(harness, tes_server):
    tes_server.tasks[TASK_ID] = _task("SYSTEM_ERROR")
    harness.check()
    assert harness.watch_for(INTERVAL + GRACE - 1)
    tes_server.tasks[TASK_ID] = _task("RUNNING")
    assert harness.watch_for(INTERVAL)
    tes_server.tasks[TASK_ID] = _task("SYSTEM_ERROR")
    assert harness.watch_for(GRACE)
    assert harness.failures == []
    assert not harness.watch_for(INTERVAL)


def test_tes_server_errors_never_fail_the_job(harness, tes_server):
    tes_server.error_status = 500
    harness.check()
    assert harness.watch_for(INTERVAL + 3 * GRACE)
    assert set(tes_server.views_requested()) == {"BASIC"}

    tes_server.stop()
    assert harness.watch_for(3 * GRACE)
    assert harness.failures == []


@pytest.mark.parametrize(
    "attribute, value",
    [
        # Resubmitted, so the job runs as another task.
        ("job_runner_external_id", "a-newer-task"),
        # Claimed by another handler to finish it.
        ("handler", "main.handler1"),
    ],
)
def test_job_resubmitted_or_claimed_elsewhere_stops_the_checks(harness, tes_server, attribute, value):
    tes_server.tasks[TASK_ID] = _task("EXECUTOR_ERROR")
    harness.check()
    harness.check_after(INTERVAL)
    setattr(harness.job, attribute, value)

    assert harness.check_after(INTERVAL) is None
    assert tes_server.views_requested() == ["BASIC"]
    assert harness.failures == []


@pytest.mark.parametrize("checked_first", [True, False], ids=["after_a_check", "before_the_first_check"])
def test_final_status_from_pulsar_outlasting_the_grace_period_keeps_the_job(harness, tes_server, checked_first):
    tes_server.tasks[TASK_ID] = _task("COMPLETE", executor_logs=[{"exit_code": 0}])
    harness.job.state = model.Job.states.RUNNING
    if checked_first:
        harness.check()
        assert harness.watch_for(INTERVAL)
    # Pulsar's message arrives; Galaxy finishes the job on a worker thread, and the job
    # stays running until that is done.
    harness.runner._update_job_state_for_status(harness.job_state_for(harness.job_wrapper), "complete")
    method, _ = harness.runner.work_queue.get_nowait()
    assert method == harness.runner.finish_job

    assert not harness.watch_for(INTERVAL + GRACE + INTERVAL)
    assert harness.failures == []


def test_tasks_sharing_an_id_on_two_tes_servers_are_watched_apart(harness, tes_server, other_tes_server, clock):
    # Nothing in the TES spec makes task ids unique across servers (tesp-api's are MongoDB ObjectIds).
    tes_server.tasks[TASK_ID] = _task("COMPLETE", executor_logs=[{"exit_code": 0}])
    other_tes_server.tasks[TASK_ID] = _task("EXECUTOR_ERROR", executor_logs=[{"exit_code": 1}])
    other_job_wrapper = FakeJobWrapper(harness.runner.app)
    other_job_wrapper.job_id = other_job_wrapper.job.id = GALAXY_JOB_ID + 1
    harness.job.state = other_job_wrapper.job.state = model.Job.states.RUNNING
    watched = [harness.job_state_for(other_job_wrapper, tes_url=other_tes_server.url), harness.job_state]
    for job_state in watched:
        harness.runner.check_watched_item(job_state)
    # Pulsar reports the first job's task; that must not end the other job's checks.
    harness.runner._update_job_state_for_status(harness.job_state_for(harness.job_wrapper), "complete")

    for _ in range(int(INTERVAL + GRACE + INTERVAL)):
        clock.now += 1
        watched = [job_state for job_state in watched if harness.runner.check_watched_item(job_state)]

    assert watched == []
    assert harness.failures == []
    [failure] = other_job_wrapper.failures
    assert failure["message"].startswith(f"TES task {TASK_ID} ended in state EXECUTOR_ERROR")


@pytest.mark.parametrize("status", ["complete", "cancelled"])
def test_late_final_status_for_a_job_failed_by_the_checks_is_ignored(harness, tes_server, status):
    tes_server.tasks[TASK_ID] = _task("COMPLETE", executor_logs=[{"exit_code": 0}])
    harness.job.state = model.Job.states.RUNNING
    harness.check()
    assert not harness.watch_for(INTERVAL + GRACE + INTERVAL)
    assert harness.job.state == model.Job.states.ERROR

    # Galaxy's message consumer was down past the grace period; Pulsar's status arrives now.
    assert harness.runner._update_job_state_for_status(harness.job_state, status) is None

    assert harness.runner.work_queue.empty()


@pytest.mark.parametrize("state", [model.Job.states.DELETING, model.Job.states.DELETED])
def test_final_status_for_a_deleted_job_still_finishes_it(harness, state):
    # Finishing a deleted job is what cleans up its working directory and outputs.
    harness.job.state = state

    assert harness.runner._update_job_state_for_status(harness.job_state, "cancelled") is None

    method, _ = harness.runner.work_queue.get_nowait()
    assert method == harness.runner.finish_job


def test_errors_while_checking_do_not_stop_the_monitor(harness, tes_server):
    tes_server.tasks[TASK_ID] = _task("RUNNING")
    harness.check()
    harness.job_wrapper.state_error = RuntimeError("database went away")
    assert harness.check_after(INTERVAL) is harness.job_state
    harness.job_wrapper.state_error = None
    assert harness.check_after(INTERVAL) is harness.job_state
    assert tes_server.views_requested() == ["BASIC"]


def test_known_secrets_are_redacted_exactly(harness, tes_server):
    no_digits_argument = "QUJDREVGR0hJSktMTU5PUFFSU1RVVldYWVphYmNkZWZn"
    executors = _executors()
    executors[2]["command"] = ["pulsar-finish", "--app_conf_base64", no_digits_argument]
    tes_server.tasks[TASK_ID] = _task(
        "COMPLETE",
        executors=executors,
        executor_logs=[
            {"exit_code": 0},
            {"exit_code": 0},
            {
                "exit_code": 0,
                "stderr": f"argv {no_digits_argument}\nconnecting with {AMQP_PASSWORD}\n{{'password': 'hunter2'}}",
            },
        ],
    )
    harness.check()
    assert not harness.watch_for(INTERVAL + GRACE + INTERVAL)

    [failure] = harness.failures
    stderr = failure["tool_stderr"]
    assert "argv [redacted]" in stderr
    assert "connecting with [redacted]" in stderr
    assert "{'password': '[redacted]'}" in stderr


def _reject_cancel_like_tesk(tes_server):
    tes_server.cancel_status = TESK_CANCEL_ENDED_TASK_STATUS
    tes_server.cancel_body = TESK_CANCEL_ENDED_TASK_BODY


def _log_messages(caplog, level):
    return [record.getMessage() for record in caplog.records if record.levelno == level]


def test_stopping_a_job_cancels_its_tes_task(harness, tes_server, caplog):
    tes_server.tasks[TASK_ID] = _task("RUNNING")
    harness.runner.stop_job(harness.job_wrapper)
    assert tes_server.requests == [(TASK_ID, "POST")]
    assert _log_messages(caplog, logging.ERROR) == []


@pytest.mark.parametrize("state", ["COMPLETE", "EXECUTOR_ERROR", "SYSTEM_ERROR", "CANCELED", "PREEMPTED", "CANCELING"])
def test_stopping_a_job_whose_task_already_ended_is_done(harness, tes_server, caplog, state):
    # TESK refuses to cancel a task that has ended. Raising would roll back the stop
    # queue's step, which then retries every second and leaves the job deleting.
    caplog.set_level(logging.INFO, logger=pulsar_runner.__name__)
    tes_server.tasks[TASK_ID] = _task(state)
    _reject_cancel_like_tesk(tes_server)
    harness.job.state = model.Job.states.DELETED

    harness.runner.stop_job(harness.job_wrapper)

    assert tes_server.views_requested() == ["POST", "BASIC"]
    assert f"({GALAXY_JOB_ID}/{TASK_ID}) TES task is {state}, nothing to cancel" in _log_messages(caplog, logging.INFO)
    assert _log_messages(caplog, logging.ERROR) == []


def test_stopping_a_job_whose_task_is_gone_is_done(harness, tes_server, caplog):
    caplog.set_level(logging.INFO, logger=pulsar_runner.__name__)
    harness.runner.stop_job(harness.job_wrapper)
    assert tes_server.views_requested() == ["POST", "BASIC"]
    assert f"({GALAXY_JOB_ID}/{TASK_ID}) TES task is NOT_FOUND, nothing to cancel" in _log_messages(
        caplog, logging.INFO
    )


@pytest.mark.parametrize("unreadable", [False, True])
def test_failing_to_cancel_a_running_task_is_logged_not_raised(harness, tes_server, caplog, unreadable):
    # Raising can't make a permanent error go away; it would only block the stop queue.
    tes_server.tasks[TASK_ID] = _task("RUNNING")
    tes_server.cancel_status = 401
    tes_server.cancel_body = {"error": "unauthorized"}
    if unreadable:
        tes_server.error_status = 500

    harness.runner.stop_job(harness.job_wrapper)

    assert tes_server.views_requested() == ["POST", "BASIC"]
    [message] = _log_messages(caplog, logging.ERROR)
    assert message.startswith(f"({GALAXY_JOB_ID}/{TASK_ID}) Failed to cancel TES task")
    assert "may still be running" in message
    assert "unauthorized" in message
    assert ("could not read its state" in message) is unreadable


def test_failing_a_job_cancels_its_tes_task_then_fails_the_job(harness, tes_server):
    tes_server.tasks[TASK_ID] = _task("RUNNING")
    harness.job.state = model.Job.states.RUNNING

    harness.runner.fail_job(harness.job_state, message="Pulsar failed to stage out the outputs")

    assert tes_server.requests == [(TASK_ID, "POST")]
    assert harness.failures == [{"message": "Pulsar failed to stage out the outputs", "tool_stderr": None}]


def test_failing_a_job_whose_task_already_ended_fails_the_job(harness, tes_server):
    # fail_job stops the job before failing it, so a refused cancel must not escape.
    tes_server.tasks[TASK_ID] = _task("EXECUTOR_ERROR")
    _reject_cancel_like_tesk(tes_server)
    harness.job.state = model.Job.states.RUNNING

    harness.runner.fail_job(harness.job_state, message="Pulsar failed to stage out the outputs")

    assert tes_server.views_requested() == ["POST", "BASIC"]
    assert harness.failures == [{"message": "Pulsar failed to stage out the outputs", "tool_stderr": None}]


def test_status_for_a_stopped_job_cancels_its_tes_task_and_finishes_it(harness, tes_server):
    tes_server.tasks[TASK_ID] = _task("RUNNING")
    harness.job.state = model.Job.states.STOPPED

    assert harness.runner._update_job_state_for_status(harness.job_state, "failed") is None

    assert tes_server.requests == [(TASK_ID, "POST")]
    method, _ = harness.runner.work_queue.get_nowait()
    assert method == harness.runner.finish_job


def test_status_for_a_stopped_job_whose_task_already_ended_finishes_it(harness, tes_server):
    tes_server.tasks[TASK_ID] = _task("COMPLETE")
    _reject_cancel_like_tesk(tes_server)
    harness.job.state = model.Job.states.STOPPED

    assert harness.runner._update_job_state_for_status(harness.job_state, "failed") is None

    assert tes_server.views_requested() == ["POST", "BASIC"]
    method, _ = harness.runner.work_queue.get_nowait()
    assert method == harness.runner.finish_job


def _runner(runner_class, **params):
    app = Mock()
    app.config.redact_email_in_job_name = False
    app.config.galaxy_infrastructure_url = "http://galaxy.example"
    app.config.server_name = SERVER_NAME
    app.config.nginx_upload_job_files_path = None
    app.security.encode_id.side_effect = lambda id, kind=None: f"encoded{id}"
    return runner_class(app, 1, **params)


def test_tes_checks_are_on_by_default():
    runner = _runner(PulsarTesJobRunner)
    assert runner.poll
    assert runner.use_mq
    assert runner.tes_status_check_interval == INTERVAL
    assert runner.tes_status_grace_period == GRACE


def test_tes_checks_are_configurable():
    runner = _runner(PulsarTesJobRunner, tes_status_check_interval="15", tes_status_grace_period="0")
    assert runner.poll
    assert runner.tes_status_check_interval == 15.0
    assert runner.tes_status_grace_period == 0.0
    assert not _runner(PulsarTesJobRunner, tes_status_check_interval="0").poll
    with pytest.raises(Exception, match="tes_status_grace_period"):
        _runner(PulsarTesJobRunner, tes_status_grace_period="-1")


def test_tes_options_are_rejected_by_other_pulsar_runners():
    with pytest.raises(Exception, match="tes_status_check_interval"):
        _runner(PulsarMQJobRunner, amqp_url="amqp://", tes_status_check_interval="15")


def test_redact_hides_credentials_but_keeps_paths_and_digests():
    digest = "sha256:" + "0123456789abcdef" * 4
    text = (
        f"pulsar-submit --base64 {JOB_BASE64} amqp://guest:s3cr3t@broker:5672// "
        f"http://galaxy/api/jobs/1/files?job_key=abc123XYZ&path=x {digest} "
        "/pulsar_staging/persisted_data/_default_-active-jobs"
    )
    redacted = redact(text)
    assert JOB_BASE64[:32] not in redacted
    assert "s3cr3t" not in redacted
    assert "abc123XYZ" not in redacted
    assert digest in redacted
    assert "/pulsar_staging/persisted_data/_default_-active-jobs" in redacted
    assert "amqp://[redacted]@broker:5672//" in redacted
