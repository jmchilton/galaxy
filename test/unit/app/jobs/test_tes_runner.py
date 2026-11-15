"""TesJobRunner: TES tasks that stage files over Galaxy's job files API, polled for state."""

import json
import os
import subprocess
from types import SimpleNamespace
from typing import Any
from unittest.mock import Mock
from urllib.parse import (
    parse_qs,
    urlparse,
)

import pytest
from pydantictes.models import TesResources

from galaxy import model
from galaxy.jobs.runners import (
    AsynchronousJobState,
    tes as tes_runner,
)
from galaxy.jobs.runners.tes import (
    build_tes_task,
    executor_env,
    job_files_url,
    staged_input_paths,
    TES_WRAPPER_SCRIPT,
    TesJobRunner,
    wrapper_script,
)

GALAXY_URL = "http://172.17.0.1:18080"
JOB_KEY = "0123456789abcdef"
TASK_ID = "d4rk5c3bf5d1q0abcdef"


def _write(path, content="x"):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as fh:
        fh.write(content)
    return str(path)


def test_job_files_url_quotes_the_path():
    url = job_files_url(GALAXY_URL + "/", "f2db41e1fa331b3e", JOB_KEY, "/data/a b&c=d+e.dat")
    parsed = urlparse(url)
    assert parsed.path == "/api/jobs/f2db41e1fa331b3e/files"
    assert parse_qs(parsed.query) == {"path": ["/data/a b&c=d+e.dat"], "job_key": [JOB_KEY]}


def test_staged_input_paths(tmp_path):
    job_dir = tmp_path / "jobs" / "7"
    tool_dir = tmp_path / "tools" / "mytool"
    dataset = _write(tmp_path / "objects" / "dataset_1.dat")
    metadata_file = _write(tmp_path / "objects" / "metadata_1.dat")
    extra_file = _write(tmp_path / "objects" / "dataset_1_files" / "sub" / "part.txt")
    script = _write(tool_dir / "helper.py")
    data_dir_file = _write(tool_dir / "data" / "table.tsv")
    _write(tool_dir / "unused.py")
    job_script = _write(job_dir / "galaxy_7.sh", f"python '{script}' --data {tool_dir}/data;\n")
    config = _write(job_dir / "working" / "config.yml", "key: value\n")
    output = _write(job_dir / "outputs" / "dataset_2.dat", "stale")
    missing = str(tmp_path / "objects" / "never_written.dat")

    staged = staged_input_paths(
        str(job_dir),
        [dataset, metadata_file, str(tmp_path / "objects" / "dataset_1_files"), missing, dataset],
        str(tool_dir),
        exclude=[output],
    )

    assert staged[:3] == [dataset, metadata_file, extra_file]
    assert set(staged[3:]) == {job_script, config, script, data_dir_file}
    assert len(staged) == len(set(staged))


def test_wrapper_script_keeps_the_exit_code_and_exits_zero(tmp_path):
    job_dir = str(tmp_path)
    work_dir_output = os.path.join(job_dir, "outputs", "dataset_3.dat")
    # Like a from_work_dir copy in Galaxy's job script: it only writes to an output that exists.
    job_script = _write(
        tmp_path / "galaxy_7.sh",
        "mkdir -p outputs working\necho tool > outputs/dataset_2.dat\necho report > working/report.html\n"
        f"if [ -f working/report.html -a -f {work_dir_output} ]; then cp working/report.html {work_dir_output}; fi\n"
        "echo out; echo err >&2\necho 3 > galaxy_7.ec\nexit 3\n",
    )
    outputs = [
        os.path.join(job_dir, "outputs", "dataset_2.dat"),
        work_dir_output,
        os.path.join(job_dir, "outputs", "tool_stderr"),
    ]
    paths = {name: os.path.join(job_dir, name) for name in ("galaxy_7.ec", "galaxy_7.o", "galaxy_7.e")}
    script = wrapper_script(
        job_dir,
        job_script,
        paths["galaxy_7.ec"],
        paths["galaxy_7.o"],
        paths["galaxy_7.e"],
        outputs,
        precreated=[work_dir_output],
    )

    result = subprocess.run(["/bin/sh", "-c", script], cwd="/", check=False)

    assert result.returncode == 0
    assert open(paths["galaxy_7.ec"]).read().strip() == "3"
    assert open(paths["galaxy_7.o"]).read() == "out\n"
    assert open(paths["galaxy_7.e"]).read() == "err\n"
    assert open(outputs[0]).read() == "tool\n"
    assert open(work_dir_output).read() == "report\n"
    assert open(outputs[2]).read() == ""
    for directory in ("home", "tmp", "metadata"):
        assert os.path.isdir(os.path.join(job_dir, directory))


def test_wrapper_script_records_the_exit_code_of_a_job_script_that_wrote_none(tmp_path):
    job_script = _write(tmp_path / "galaxy_7.sh", "exit 7\n")
    ec = str(tmp_path / "galaxy_7.ec")
    script = wrapper_script(str(tmp_path), job_script, ec, str(tmp_path / "o"), str(tmp_path / "e"), [ec])

    assert subprocess.run(["/bin/sh", "-c", script], check=False).returncode == 0
    assert open(ec).read().strip() == "7"


def test_build_tes_task():
    job_dir = "/galaxy/jobs/000/7"
    resources = TesResources(cpu_cores=2, ram_gb=4)

    task = build_tes_task(
        name="galaxy-7",
        image="quay.io/biocontainers/fastp:1.4.0--h43da1c4_0",
        job_directory=job_dir,
        input_paths=["/galaxy/objects/dataset_1.dat", f"{job_dir}/galaxy_7.sh"],
        output_paths=[f"{job_dir}/outputs/dataset_2.dat", f"{job_dir}/galaxy_7.ec"],
        wrapper="#!/bin/sh\nexit 0\n",
        url_for=lambda path: job_files_url(GALAXY_URL, "abc", JOB_KEY, path),
        resources=resources,
        env=executor_env(resources),
    )

    document = json.loads(task.model_dump_json(exclude_none=True))
    assert document["volumes"] == [job_dir]
    inputs = document["inputs"]
    assert [i["path"] for i in inputs] == [
        "/galaxy/objects/dataset_1.dat",
        f"{job_dir}/galaxy_7.sh",
        f"{job_dir}/{TES_WRAPPER_SCRIPT}",
    ]
    assert inputs[0]["url"] == job_files_url(GALAXY_URL, "abc", JOB_KEY, "/galaxy/objects/dataset_1.dat")
    assert inputs[2] == {"path": f"{job_dir}/{TES_WRAPPER_SCRIPT}", "type": "FILE", "content": "#!/bin/sh\nexit 0\n"}
    assert [(o["path"], o["type"]) for o in document["outputs"]] == [
        (f"{job_dir}/outputs/dataset_2.dat", "FILE"),
        (f"{job_dir}/galaxy_7.ec", "FILE"),
    ]
    assert document["outputs"][1]["url"] == job_files_url(GALAXY_URL, "abc", JOB_KEY, f"{job_dir}/galaxy_7.ec")
    assert document["executors"] == [
        {
            "image": "quay.io/biocontainers/fastp:1.4.0--h43da1c4_0",
            "command": ["/bin/sh", f"{job_dir}/{TES_WRAPPER_SCRIPT}"],
            "workdir": job_dir,
            "env": {"GALAXY_SLOTS": "2", "GALAXY_MEMORY_MB": "4096"},
        }
    ]
    assert document["resources"] == {"cpu_cores": 2, "ram_gb": 4.0, "backend_parameters_strict": False}


class _Runner(TesJobRunner):
    def __init__(self):
        self.tes_poll_interval = 10.0
        self._next_checks = {}
        self.app = SimpleNamespace(security=SimpleNamespace(encode_id=lambda job_id, kind=None: JOB_KEY))
        self.finished: list[Any] = []
        self.failed: list[Any] = []

    def mark_as_finished(self, job_state):
        self.finished.append(job_state)

    def fail_job(self, job_state, exception=False, message="Job failed", full_status=None):
        self.failed.append((message, full_status, job_state.stop_job))


@pytest.fixture
def clock(monkeypatch):
    now = [1000.0]
    monkeypatch.setattr(tes_runner, "monotonic", lambda: now[0])
    return now


@pytest.fixture
def tes(monkeypatch):
    server = SimpleNamespace(state="QUEUED", task=None, checks=0)

    def fetch(client, task_id):
        assert task_id == TASK_ID
        server.checks += 1
        return server.state

    client = Mock()
    client.get_task.side_effect = lambda task_id, view: server.task
    monkeypatch.setattr(tes_runner, "fetch_tes_task_state", fetch)
    monkeypatch.setattr(tes_runner, "tes_client_from_params", lambda params: client)
    return server


def _job_state(galaxy_state=model.Job.states.QUEUED):
    job_wrapper = Mock()
    job_wrapper.job_id = 7
    job_wrapper.get_id_tag.return_value = "7"
    job_wrapper.get_state.return_value = galaxy_state
    job_state = AsynchronousJobState.__new__(AsynchronousJobState)
    job_state.job_wrapper = job_wrapper
    job_state.job_destination = SimpleNamespace(params={"tes_url": "http://127.0.0.1:18000/"})
    job_state.job_id = TASK_ID
    job_state._running = False
    job_state.start_time = None
    job_state.stop_job = True
    return job_state


def test_poll_marks_running_once_then_finishes_on_complete(tes, clock):
    runner = _Runner()
    job_state = _job_state()

    assert runner.check_watched_item(job_state) is job_state
    tes.state = "RUNNING"
    assert runner.check_watched_item(job_state) is job_state  # within the poll interval: no check
    assert tes.checks == 1
    clock[0] += 10
    assert runner.check_watched_item(job_state) is job_state
    clock[0] += 10
    assert runner.check_watched_item(job_state) is job_state
    job_state.job_wrapper.change_state.assert_called_once_with(model.Job.states.RUNNING)
    tes.state = "COMPLETE"
    clock[0] += 10
    assert runner.check_watched_item(job_state) is None
    assert runner.finished == [job_state]
    assert runner.failed == []


def test_poll_fails_the_job_with_the_redacted_executor_log(tes, clock):
    runner = _Runner()
    job_state = _job_state(model.Job.states.RUNNING)
    tes.state = "EXECUTOR_ERROR"
    tes.task = SimpleNamespace(
        executors=[SimpleNamespace(image="quay.io/biocontainers/fastp:1.4.0", command=["/bin/sh", "/w.sh"])],
        logs=[
            SimpleNamespace(
                logs=[SimpleNamespace(exit_code=137, stderr=f"killed\nGET ...&job_key={JOB_KEY}")],
                system_logs=[],
            )
        ],
    )

    assert runner.check_watched_item(job_state) is None

    [(message, full_status, stop_job)] = runner.failed
    assert message == f"TES task {TASK_ID} ended in state EXECUTOR_ERROR. Executor 0 exited with code 137."
    assert JOB_KEY not in full_status["stderr"]
    assert "killed" in full_status["stderr"]
    assert stop_job is False


def test_poll_stops_watching_a_stopped_job(tes, clock):
    runner = _Runner()
    job_state = _job_state(model.Job.states.DELETING)

    assert runner.check_watched_item(job_state) is None
    assert tes.checks == 0
    assert runner.finished == runner.failed == []
