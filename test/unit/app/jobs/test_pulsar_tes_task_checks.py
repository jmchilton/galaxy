"""PulsarTesJobRunner against a fake TES server.

The runner talks to the fake TES server over HTTP through pydantic-tes, the
client Pulsar uses to submit the tasks.
"""

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
from urllib.parse import urlparse

import pytest

from galaxy import model
from galaxy.jobs import MinimalJobWrapper
from galaxy.jobs.job_destination import JobDestination
from galaxy.jobs.runners import AsynchronousJobState
from galaxy.jobs.runners.pulsar import (
    PulsarMQJobRunner,
    PulsarTesJobRunner,
)

TASK_ID = "d4rk5c3bf5d1q0abcdef"
GALAXY_JOB_ID = 42
SERVER_NAME = "main.handler0"
AMQP_PASSWORD = "Br0kerPassword"
STAGING_IMAGE = "galaxy/pulsar-pod-staging:0.15.0.2"


class FakeTesServer:
    """Answers ``POST /v1/tasks/{id}:cancel`` with ``cancel_status`` and ``cancel_body`` for known tasks."""

    def __init__(self):
        self.tasks: dict[str, dict[str, Any]] = {}
        self.requests: list[tuple[str, str]] = []
        self.cancel_status = 200
        self.cancel_body: dict[str, Any] = {}
        server = self

        class Handler(BaseHTTPRequestHandler):
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

    def stop(self):
        self.httpd.shutdown()
        self.httpd.server_close()


@pytest.fixture
def tes_server():
    server = FakeTesServer()
    yield server
    server.stop()


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
    """Just what ``AsynchronousJobState`` and ``fail_job`` use; records failures."""

    def __init__(self, app):
        self.app = app
        self.job = FakeJob()
        self.job_id = GALAXY_JOB_ID
        self.tool = FakeTool()
        self.user = None
        self.guest_ports: list[int] = []
        self.failures: list[dict[str, Any]] = []

    def get_id_tag(self):
        return str(self.job_id)

    def get_state(self):
        return self.job.state

    def get_job(self):
        return self.job

    def reclaim_ownership(self):
        pass

    def fail(self, message, exception=False, tool_stdout="", tool_stderr="", **kwds):
        self.failures.append({"message": message, "tool_stderr": tool_stderr})
        self.job.state = model.Job.states.ERROR


class Harness:
    """A TES runner with one job."""

    def __init__(self, tes_server):
        self.tes_server = tes_server
        self.runner = _runner(PulsarTesJobRunner, amqp_url=f"amqp://galaxy:{AMQP_PASSWORD}@broker:5672//")
        self.runner.work_queue = Queue()
        self.runner._init_client_manager()
        self.job_wrapper = FakeJobWrapper(self.runner.app)
        self.job = self.job_wrapper.job
        self.job.destination_params = self.destination_params()
        self.job_state = self.job_state_for(self.job_wrapper)

    def destination_params(self):
        return {"tes_url": self.tes_server.url, "pulsar_container_image": STAGING_IMAGE}

    def job_state_for(self, job_wrapper):
        destination = JobDestination(params=self.destination_params())
        return AsynchronousJobState(
            job_wrapper=cast(MinimalJobWrapper, job_wrapper), job_destination=destination, job_id=TASK_ID
        )

    @property
    def failures(self):
        return self.job_wrapper.failures


@pytest.fixture
def harness(tes_server):
    return Harness(tes_server)


def _log_messages(caplog, level):
    return [record.getMessage() for record in caplog.records if record.levelno == level]


def _task(state):
    return {"id": TASK_ID, "state": state, "name": "pulsar-42", "executors": []}


def test_stopping_a_job_cancels_its_tes_task(harness, tes_server, caplog):
    tes_server.tasks[TASK_ID] = _task("RUNNING")
    harness.runner.stop_job(harness.job_wrapper)
    assert tes_server.requests == [(TASK_ID, "POST")]
    assert _log_messages(caplog, logging.ERROR) == []


def test_failing_a_job_cancels_its_tes_task_then_fails_the_job(harness, tes_server):
    tes_server.tasks[TASK_ID] = _task("RUNNING")
    harness.job.state = model.Job.states.RUNNING

    harness.runner.fail_job(harness.job_state, message="Pulsar failed to stage out the outputs")

    assert tes_server.requests == [(TASK_ID, "POST")]
    assert harness.failures == [{"message": "Pulsar failed to stage out the outputs", "tool_stderr": None}]


def test_status_for_a_stopped_job_cancels_its_tes_task_and_finishes_it(harness, tes_server):
    tes_server.tasks[TASK_ID] = _task("RUNNING")
    harness.job.state = model.Job.states.STOPPED

    assert harness.runner._update_job_state_for_status(harness.job_state, "failed") is None

    assert tes_server.requests == [(TASK_ID, "POST")]
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


def test_tes_options_are_rejected_by_other_pulsar_runners():
    with pytest.raises(Exception, match="tes_status_check_interval"):
        _runner(PulsarMQJobRunner, amqp_url="amqp://", tes_status_check_interval="15")
