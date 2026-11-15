"""Fakes for testing Galaxy's TES job runners: a TES server over HTTP and just enough of a job."""

import copy
import json
import threading
from dataclasses import (
    dataclass,
    field,
)
from http.server import (
    BaseHTTPRequestHandler,
    ThreadingHTTPServer,
)
from typing import Any
from unittest.mock import Mock
from urllib.parse import (
    parse_qs,
    urlparse,
)

from galaxy import model
from galaxy.jobs.job_destination import JobDestination

TASK_ID = "d4rk5c3bf5d1q0abcdef"
GALAXY_JOB_ID = 42
SERVER_NAME = "main.handler0"


class FakeTesServer:
    """Serves ``GET /v1/tasks/{id}`` the way Funnel does: MINIMAL has the id and state only, BASIC drops
    stdout, stderr and system logs.

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
        # A short poll interval keeps stop() from waiting half a second.
        self.thread = threading.Thread(target=self.httpd.serve_forever, args=(0.01,), daemon=True)
        self.thread.start()

    @staticmethod
    def view(task, view):
        if view == "MINIMAL":
            return {key: task[key] for key in ("id", "state") if key in task}
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


class Clock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now


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
    """Just what ``AsynchronousJobState``, the TES runners and ``fail_job`` use; records failures.

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
        self.working_directory: str | None = None
        self.job_destination: JobDestination | None = None
        # What check_limits reports, e.g. ("walltime_reached", message); None means no limits.
        self.limit_state: tuple[str, str] | None = None

    def get_id_tag(self):
        return str(self.job_id)

    def get_state(self):
        self.state_reads += 1
        if self.state_error:
            raise self.state_error
        return self.job.state

    def change_state(self, state, **kwds):
        self.job.state = state

    def get_job(self):
        return self.job

    def has_limits(self):
        return self.limit_state is not None

    def check_limits(self, runtime=None):
        return self.limit_state

    def reclaim_ownership(self):
        pass

    def fail(self, message, exception=False, tool_stdout="", tool_stderr="", **kwds):
        self.failures.append({"message": message, "tool_stderr": tool_stderr})
        self.job.state = model.Job.states.ERROR


def fake_runner(runner_class, **params):
    """A runner of ``runner_class`` on a mock app, with no threads started."""
    app = Mock()
    app.config.redact_email_in_job_name = False
    app.config.galaxy_infrastructure_url = "http://galaxy.example"
    app.config.server_name = SERVER_NAME
    app.config.nginx_upload_job_files_path = None
    app.security.encode_id.side_effect = lambda id, kind=None: f"encoded{id}"
    return runner_class(app, 1, **params)
