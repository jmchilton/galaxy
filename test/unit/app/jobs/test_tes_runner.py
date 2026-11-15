"""TesJobRunner: TES tasks that stage files over Galaxy's job files API, polled for state."""

import json
import logging
import os
import subprocess
import time
from queue import Queue
from typing import cast
from urllib.parse import (
    parse_qs,
    urlparse,
)

import pytest
from pydantictes.models import TesResources

from galaxy import model
from galaxy.jobs import MinimalJobWrapper
from galaxy.jobs.job_destination import JobDestination
from galaxy.jobs.runners import (
    AsynchronousJobState,
    tes as tes_runner,
)
from galaxy.jobs.runners.tes import (
    build_tes_task,
    directory_output_paths,
    executor_env,
    job_files_url,
    signed_job_files_url_for,
    staged_input_paths,
    TES_WRAPPER_SCRIPT,
    TesJobRunner,
    wrapper_script,
)
from galaxy.jobs.runners.util import tes_task
from galaxy.security.idencoding import IdEncodingHelper
from galaxy.security.job_files_tokens import (
    JOB_FILES_DIRECTORY_WRITE,
    JOB_FILES_READ,
    JOB_FILES_WRITE,
    verify_job_files_token,
)
from .tes_fakes import (
    Clock,
    fake_runner,
    FakeJobWrapper,
    FakeTesServer,
    GALAXY_JOB_ID,
    TASK_ID,
)

GALAXY_URL = "http://172.17.0.1:18080"
TOKEN = "1763200000.c2lnbmF0dXJl"
IMAGE = "quay.io/biocontainers/fastp:1.4.0--h43da1c4_0"


def _write(path, content="x"):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as fh:
        fh.write(content)
    return str(path)


def test_signed_urls_carry_a_token_for_their_path_and_scope():
    security = IdEncodingHelper(id_secret="a test secret, not a real one")
    expires = 1_763_200_000
    url_for = signed_job_files_url_for(GALAXY_URL + "/", security, 7, expires)
    path = "/galaxy/jobs/000/7/working/a b&c=d+e.dat"

    for scope in (JOB_FILES_READ, JOB_FILES_WRITE, JOB_FILES_DIRECTORY_WRITE):
        url = url_for(path, scope)
        parsed = urlparse(url)
        assert parsed.path == f"/api/jobs/{security.encode_id(7)}/files"
        query = parse_qs(parsed.query)
        assert set(query) == {"path", "job_token"}
        assert query["path"] == [path]
        assert verify_job_files_token(security, 7, path, scope, query["job_token"][0], now=expires)
        assert security.encode_id(7, kind="jobs_files") not in url


def _staging_fixture(tmp_path):
    job_dir = tmp_path / "jobs" / "7"
    tool_dir = tmp_path / "tools" / "mytool"
    dataset = _write(tmp_path / "objects" / "dataset_1.dat")
    metadata_file = _write(tmp_path / "objects" / "metadata_1.dat")
    extra_file = _write(tmp_path / "objects" / "dataset_1_files" / "sub" / "part.txt")
    script = _write(tool_dir / "main.py")
    data_dir_file = _write(tool_dir / "data" / "table.tsv")
    # Imported by main.py, never named in the job's files.
    helper = _write(tool_dir / "helper.py")
    _write(tool_dir / "test-data" / "input.fastq")
    _write(tool_dir / ".hg" / "store")
    job_script = _write(job_dir / "galaxy_7.sh", f"python '{script}' --data {tool_dir}/data;\n")
    config = _write(job_dir / "working" / "config.yml", "key: value\n")
    output = _write(job_dir / "outputs" / "dataset_2.dat", "stale")
    missing = str(tmp_path / "objects" / "never_written.dat")
    inputs = [dataset, metadata_file, str(tmp_path / "objects" / "dataset_1_files"), missing, dataset]
    staged = staged_input_paths(str(job_dir), inputs, str(tool_dir), exclude=[output])
    return staged, [dataset, metadata_file, extra_file], {job_script, config, script, data_dir_file}, helper


def test_staged_input_paths(tmp_path):
    staged, input_files, referenced, helper = _staging_fixture(tmp_path)

    assert staged[:3] == input_files
    # The whole tool directory, without test data and hidden directories.
    assert set(staged[3:]) == referenced | {helper}
    assert len(staged) == len(set(staged))


def test_staged_input_paths_of_a_large_tool_directory(tmp_path, monkeypatch):
    monkeypatch.setattr(tes_runner, "MAX_TOOL_DIRECTORY_FILES", 2)
    staged, input_files, referenced, _ = _staging_fixture(tmp_path)

    assert staged[:3] == input_files
    assert set(staged[3:]) == referenced


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
    directories = [f"{job_dir}/working", f"{job_dir}/outputs/dataset_2_files"]

    task = build_tes_task(
        name="galaxy-7",
        image=IMAGE,
        job_directory=job_dir,
        input_paths=["/galaxy/objects/dataset_1.dat", f"{job_dir}/galaxy_7.sh"],
        output_paths=[f"{job_dir}/outputs/dataset_2.dat", f"{job_dir}/galaxy_7.ec"],
        wrapper="#!/bin/sh\nexit 0\n",
        url_for=lambda path, scope: job_files_url(GALAXY_URL, "abc", path, f"{scope}-token"),
        resources=resources,
        env=executor_env(resources),
        directory_paths=directories,
    )

    document = json.loads(task.model_dump_json(exclude_none=True))
    assert document["volumes"] == [job_dir]
    assert document["inputs"] == [
        {
            "url": job_files_url(GALAXY_URL, "abc", "/galaxy/objects/dataset_1.dat", "r-token"),
            "path": "/galaxy/objects/dataset_1.dat",
            "type": "FILE",
        },
        {
            "url": job_files_url(GALAXY_URL, "abc", f"{job_dir}/galaxy_7.sh", "r-token"),
            "path": f"{job_dir}/galaxy_7.sh",
            "type": "FILE",
        },
        {"path": f"{job_dir}/{TES_WRAPPER_SCRIPT}", "type": "FILE", "content": "#!/bin/sh\nexit 0\n"},
    ]
    assert [(o["path"], o["type"], o["url"]) for o in document["outputs"]] == [
        *(
            (path, "FILE", job_files_url(GALAXY_URL, "abc", path, "w-token"))
            for path in (f"{job_dir}/outputs/dataset_2.dat", f"{job_dir}/galaxy_7.ec")
        ),
        *((path, "DIRECTORY", job_files_url(GALAXY_URL, "abc", path, "d-token")) for path in directories),
    ]
    assert document["executors"] == [
        {
            "image": IMAGE,
            "command": ["/bin/sh", f"{job_dir}/{TES_WRAPPER_SCRIPT}"],
            "workdir": job_dir,
            "env": {"GALAXY_SLOTS": "2", "GALAXY_MEMORY_MB": "4096"},
        }
    ]
    assert document["resources"]["cpu_cores"] == 2
    assert document["resources"]["ram_gb"] == 4.0


def test_directory_output_paths(tmp_path):
    job_dir = str(tmp_path / "jobs" / "7")
    extra_files = os.path.join(job_dir, "outputs", "dataset_2_files")

    assert directory_output_paths(job_dir, [extra_files, extra_files]) == [
        os.path.join(job_dir, "working"),
        extra_files,
    ]
    with pytest.raises(Exception, match="outside the job directory"):
        directory_output_paths(job_dir, [str(tmp_path / "objects" / "dataset_2_files")])


def test_wrapper_script_creates_directory_outputs_and_replaces_their_symlinks(tmp_path):
    job_dir = str(tmp_path / "job")
    working = os.path.join(job_dir, "working")
    extra_files = os.path.join(job_dir, "outputs", "dataset_2_files")
    elsewhere = _write(tmp_path / "elsewhere.txt", "outside")
    job_script = _write(
        tmp_path / "job" / "galaxy_7.sh",
        "mkdir -p working/sub\necho discovered > working/sub/out_1.txt\n"
        f"ln -s {elsewhere} working/sub/link\nln -s out_1.txt working/sub/alias.txt\n"
        f"ln -s /nonexistent {extra_files}/dangling\necho page > {extra_files}/index.html\n"
        f"ln -s index.html {extra_files}/default.html\nln -s ../../working/sub {extra_files}/subdir\n",
    )
    ec = os.path.join(job_dir, "galaxy_7.ec")
    script = wrapper_script(
        job_dir,
        job_script,
        ec,
        os.path.join(job_dir, "o"),
        os.path.join(job_dir, "e"),
        [ec],
        directories=[working, extra_files],
    )

    assert subprocess.run(["/bin/sh", "-c", script], check=False).returncode == 0
    assert open(os.path.join(working, "sub", "out_1.txt")).read() == "discovered\n"
    assert open(os.path.join(extra_files, "index.html")).read() == "page\n"
    # TESK refuses a DIRECTORY output with any symlink in it, Funnel one that leaves the task.
    # Links to files in the job directory become copies, so their contents still go back.
    alias = os.path.join(working, "sub", "alias.txt")
    default = os.path.join(extra_files, "default.html")
    for copy in (alias, default):
        assert not os.path.islink(copy)
    assert open(alias).read() == "discovered\n"
    assert open(default).read() == "page\n"
    # Links that leave the job directory, dangle or name a directory are removed.
    for removed in ("dangling", "subdir"):
        assert not os.path.lexists(os.path.join(extra_files, removed))
    assert not os.path.lexists(os.path.join(working, "sub", "link"))
    assert open(elsewhere).read() == "outside"
    assert not [name for name in os.listdir(os.path.join(working, "sub")) if name.endswith(".galaxy_copy")]


@pytest.fixture
def tes_server():
    server = FakeTesServer()
    yield server
    server.stop()


@pytest.fixture
def other_tes_server():
    server = FakeTesServer()
    yield server
    server.stop()


@pytest.fixture
def clock(monkeypatch):
    clock = Clock()
    monkeypatch.setattr(tes_runner, "monotonic", clock)
    return clock


@pytest.fixture
def runner():
    runner = fake_runner(TesJobRunner)
    runner.work_queue = Queue()
    return runner


def _job_wrapper(runner, tes_url, state=model.Job.states.QUEUED, working_directory=None) -> FakeJobWrapper:
    job_wrapper = FakeJobWrapper(runner.app)
    job_wrapper.job.state = state
    job_wrapper.job.destination_params = {"tes_url": tes_url}
    job_wrapper.job_destination = JobDestination(params=job_wrapper.job.destination_params)
    job_wrapper.working_directory = working_directory
    return job_wrapper


def _watched(job_wrapper: FakeJobWrapper) -> AsynchronousJobState:
    return AsynchronousJobState(
        job_wrapper=cast(MinimalJobWrapper, job_wrapper), job_destination=job_wrapper.job_destination, job_id=TASK_ID
    )


def _task(state, executor_logs=None):
    task = {"id": TASK_ID, "state": state, "name": "galaxy-42", "executors": [{"image": IMAGE, "command": ["/bin/sh"]}]}
    if executor_logs is not None:
        task["logs"] = [{"logs": executor_logs, "system_logs": []}]
    return task


def _finished(runner) -> list[AsynchronousJobState]:
    """Job states the runner queued for ``finish_job``."""
    finished = []
    while not runner.work_queue.empty():
        method, job_state = runner.work_queue.get_nowait()
        assert method == runner.finish_job
        finished.append(job_state)
    return finished


def test_poll_follows_the_task_to_running_then_finishes_the_job(runner, tes_server, clock):
    job_wrapper = _job_wrapper(runner, tes_server.url)
    job_state = _watched(job_wrapper)
    tes_server.tasks[TASK_ID] = _task("QUEUED")

    assert runner.check_watched_item(job_state) is job_state
    tes_server.tasks[TASK_ID] = _task("RUNNING")
    assert runner.check_watched_item(job_state) is job_state  # within the poll interval: no check
    assert len(tes_server.requests) == 1
    assert job_wrapper.job.state == model.Job.states.QUEUED
    clock.now += 10
    assert runner.check_watched_item(job_state) is job_state
    assert job_wrapper.job.state == model.Job.states.RUNNING
    assert job_state.running
    tes_server.tasks[TASK_ID] = _task("COMPLETE")
    clock.now += 10
    assert runner.check_watched_item(job_state) is None

    assert _finished(runner) == [job_state]
    assert job_wrapper.failures == []


def test_tasks_sharing_an_id_on_two_tes_servers_are_followed_apart(runner, tes_server, other_tes_server, clock):
    # Nothing makes task ids unique across TES servers (tesp-api's are MongoDB ObjectIds).
    tes_server.tasks[TASK_ID] = _task("RUNNING")
    other_tes_server.tasks[TASK_ID] = _task("COMPLETE")
    first = _watched(_job_wrapper(runner, tes_server.url))
    other_job_wrapper = _job_wrapper(runner, other_tes_server.url)
    other_job_wrapper.job_id = other_job_wrapper.job.id = GALAXY_JOB_ID + 1
    second = _watched(other_job_wrapper)

    assert runner.check_watched_item(first) is first
    assert runner.check_watched_item(second) is None

    assert _finished(runner) == [second]


def test_job_over_its_walltime_fails_and_its_task_is_cancelled(runner, tes_server, clock):
    job_wrapper = _job_wrapper(runner, tes_server.url, state=model.Job.states.RUNNING)
    job_state = _watched(job_wrapper)
    job_state.running = True
    tes_server.tasks[TASK_ID] = _task("RUNNING")
    job_wrapper.limit_state = ("walltime_reached", "Job ran longer than the maximum allowed")

    # Galaxy asks the job wrapper for its limits on every 20th check of a running job.
    results = [runner.check_watched_item(job_state) for _ in range(20)]

    assert results == [job_state] * 19 + [None]
    assert runner.work_queue.get_nowait() == (runner.fail_job, job_state)
    assert job_state.fail_message == "Job ran longer than the maximum allowed"
    # fail_job cancels the task.
    assert job_state.stop_job


def test_failed_task_fails_the_job_with_its_redacted_executor_log(runner, tes_server, clock):
    job_wrapper = _job_wrapper(runner, tes_server.url, state=model.Job.states.RUNNING)
    tes_server.tasks[TASK_ID] = _task(
        "EXECUTOR_ERROR", executor_logs=[{"exit_code": 137, "stderr": f"killed\nPUT ...&job_token={TOKEN}"}]
    )

    assert runner.check_watched_item(_watched(job_wrapper)) is None

    [failure] = job_wrapper.failures
    assert failure["message"] == f"TES task {TASK_ID} ended in state EXECUTOR_ERROR. Executor 0 exited with code 137."
    assert "killed" in failure["tool_stderr"]
    assert TOKEN not in failure["tool_stderr"]
    # The logs are read from the FULL view, and the ended task isn't cancelled.
    assert tes_server.views_requested() == ["MINIMAL", "FULL"]


def test_task_unknown_to_the_tes_server_fails_the_job(runner, tes_server, clock):
    job_wrapper = _job_wrapper(runner, tes_server.url, state=model.Job.states.RUNNING)

    assert runner.check_watched_item(_watched(job_wrapper)) is None

    assert [failure["message"] for failure in job_wrapper.failures] == [
        f"The TES server has no record of task {TASK_ID}."
    ]
    assert tes_server.views_requested() == ["MINIMAL"]


def test_tes_server_errors_never_fail_the_job(runner, tes_server, clock):
    job_wrapper = _job_wrapper(runner, tes_server.url, state=model.Job.states.RUNNING)
    job_state = _watched(job_wrapper)
    tes_server.tasks[TASK_ID] = _task("COMPLETE")
    tes_server.error_status = 503

    assert runner.check_watched_item(job_state) is job_state
    tes_server.error_status = None
    clock.now += 10
    assert runner.check_watched_item(job_state) is None

    assert job_wrapper.failures == []
    assert _finished(runner) == [job_state]


def test_a_tes_server_that_hangs_does_not_stall_the_monitor(runner, tes_server, clock, monkeypatch):
    job_wrapper = _job_wrapper(runner, tes_server.url, state=model.Job.states.RUNNING)
    job_state = _watched(job_wrapper)
    tes_server.tasks[TASK_ID] = _task("COMPLETE")
    tes_server.delay = 5
    monkeypatch.setattr(tes_task, "TES_STATE_REQUEST_TIMEOUT", 0.1)

    started = time.monotonic()
    assert runner.check_watched_item(job_state) is job_state
    assert time.monotonic() - started < 2

    assert job_wrapper.failures == []
    assert _finished(runner) == []


def test_poll_stops_watching_a_stopped_job(runner, tes_server, clock):
    job_wrapper = _job_wrapper(runner, tes_server.url, state=model.Job.states.DELETING)

    assert runner.check_watched_item(_watched(job_wrapper)) is None

    assert tes_server.requests == []
    assert job_wrapper.failures == []
    assert _finished(runner) == []


@pytest.fixture
def info_logs(caplog):
    caplog.set_level(logging.INFO, logger=tes_runner.__name__)
    return caplog


def test_stop_job_cancels_the_task(runner, tes_server, info_logs):
    tes_server.tasks[TASK_ID] = _task("RUNNING")

    runner.stop_job(_job_wrapper(runner, tes_server.url))

    assert tes_server.requests == [(TASK_ID, "POST")]
    assert "Cancelled TES task" in info_logs.text


def test_stop_job_of_an_ended_task_is_a_no_op(runner, tes_server, info_logs):
    # TESK answers 400 to cancelling a task that has ended.
    tes_server.tasks[TASK_ID] = _task("COMPLETE")
    tes_server.cancel_status = 400
    tes_server.cancel_body = {"title": "Bad Request", "status": 400}

    runner.stop_job(_job_wrapper(runner, tes_server.url))

    assert tes_server.views_requested() == ["POST", "MINIMAL"]
    assert "TES task is COMPLETE, nothing to cancel" in info_logs.text
    assert "may still be running" not in info_logs.text


def test_stop_job_reports_a_task_that_may_still_run(runner, tes_server, info_logs):
    tes_server.tasks[TASK_ID] = _task("RUNNING")
    tes_server.cancel_status = 502

    runner.stop_job(_job_wrapper(runner, tes_server.url))

    assert "Failed to cancel TES task in state RUNNING, it may still be running" in info_logs.text


def test_stop_job_without_a_task_does_nothing(runner, tes_server):
    job_wrapper = _job_wrapper(runner, tes_server.url)
    job_wrapper.job.job_runner_external_id = None

    runner.stop_job(job_wrapper)

    assert tes_server.requests == []


@pytest.mark.parametrize("galaxy_state", [model.Job.states.QUEUED, model.Job.states.RUNNING])
def test_recover_watches_the_existing_task_until_it_finishes(runner, tes_server, clock, tmp_path, galaxy_state):
    """After a Galaxy restart the job's task is polled again, not resubmitted, and the job finishes from it."""
    job_wrapper = _job_wrapper(runner, tes_server.url, state=galaxy_state, working_directory=str(tmp_path))

    runner.recover(job_wrapper.job, job_wrapper)

    job_state = runner.monitor_queue.get_nowait()
    assert job_state.job_id == TASK_ID
    assert job_state.running == (galaxy_state == model.Job.states.RUNNING)
    # The exit code and streams the task uploads are read from the usual job directory files.
    assert job_state.exit_code_file == os.path.join(str(tmp_path), f"galaxy_{GALAXY_JOB_ID}.ec")
    assert job_state.output_file == os.path.join(str(tmp_path), f"galaxy_{GALAXY_JOB_ID}.o")
    tes_server.tasks[TASK_ID] = _task("COMPLETE")
    assert runner.check_watched_item(job_state) is None
    assert _finished(runner) == [job_state]
    assert tes_server.requests == [(TASK_ID, "MINIMAL")]


def test_recover_without_a_task_id_fails_the_job(runner, tes_server):
    job_wrapper = _job_wrapper(runner, tes_server.url, state=model.Job.states.RUNNING)
    job_wrapper.job.job_runner_external_id = None

    runner.recover(job_wrapper.job, job_wrapper)

    assert [failure["message"] for failure in job_wrapper.failures] == [
        "The job's TES task id was lost, can't recover it."
    ]
    assert runner.monitor_queue.empty()
