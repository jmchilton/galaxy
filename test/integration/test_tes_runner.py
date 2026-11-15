"""Run jobs with the TES-native runner against a fake TES server that runs each task on this host.

The fake does with a task what a TES worker does: it fetches every input from its URL, runs the
executor's command, and uploads every output with a PUT - one per file below a DIRECTORY output,
as Funnel and TESK do. Tasks share Galaxy's disk here, so the fake compares each input with
Galaxy's file instead of writing it, removes each output before uploading it, and removes every
other file the task wrote, as if it had stayed on the worker. A job that needs a file the runner
doesn't stage in or out fails.
"""

import json
import os
import subprocess
import threading
import uuid
from http.server import (
    BaseHTTPRequestHandler,
    ThreadingHTTPServer,
)
from typing import (
    Any,
    ClassVar,
)
from urllib.parse import (
    parse_qs,
    quote,
    urlsplit,
    urlunsplit,
)

import requests

from galaxy_test.base.populators import DatasetPopulator
from galaxy_test.driver import integration_util

JOB_CONF_TEMPLATE = """
runners:
  local:
    load: galaxy.jobs.runners.local:LocalJobRunner
    workers: 1
  tes:
    load: galaxy.jobs.runners.tes:TesJobRunner
    workers: 1
    tes_poll_interval: 0.2

execution:
  default: tes
  environments:
    local:
      runner: local
    tes:
      runner: tes
      tes_url: {tes_url}
      docker_enabled: true
      docker_default_container_id: busybox:1.36.1-glibc
      outputs_to_working_directory: true
      tes_directory_outputs: true

tools:
- class: local
  environment: local
"""


class LocalTesServer:
    """Accepts TES tasks over HTTP and runs each in a thread, as the module docstring describes."""

    def __init__(self) -> None:
        self.tasks: dict[str, dict[str, Any]] = {}
        server = self

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self):
                path = urlsplit(self.path).path
                if path.endswith(":cancel"):
                    # Every task here ends on its own, soon.
                    self._send(200, {})
                    return
                # Servers leave out the fields a client sent as null.
                task = _without_nulls(json.loads(self.rfile.read(int(self.headers["Content-Length"]))))
                task_id = uuid.uuid4().hex
                server.tasks[task_id] = {**task, "id": task_id, "state": "QUEUED"}
                threading.Thread(target=server.run, args=(task_id,), daemon=True).start()
                self._send(200, {"id": task_id})

            def do_GET(self):
                task_id = urlsplit(self.path).path.rsplit("/", 1)[-1]
                if task := server.tasks.get(task_id):
                    self._send(200, task)
                else:
                    self._send(404, {"error": f"task not found: {task_id}"})

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
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()

    def run(self, task_id: str) -> None:
        task = self.tasks[task_id]
        self.tasks[task_id] = {**task, "state": "RUNNING"}
        try:
            _run_task(task)
        except Exception as e:
            log = {"logs": [], "system_logs": [f"{type(e).__name__}: {e}"]}
            self.tasks[task_id] = {**task, "state": "SYSTEM_ERROR", "logs": [log]}
        else:
            self.tasks[task_id] = {**task, "state": "COMPLETE"}

    def task_for_job(self, job_id: int) -> dict[str, Any]:
        [task] = (task for task in self.tasks.values() if task["name"] == f"galaxy-{job_id}")
        return task

    def stop(self) -> None:
        self.httpd.shutdown()
        self.httpd.server_close()


def _without_nulls(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: _without_nulls(item) for key, item in value.items() if item is not None}
    if isinstance(value, list):
        return [_without_nulls(item) for item in value]
    return value


def _run_task(task: dict[str, Any]) -> None:
    for task_input in task["inputs"]:
        if "content" in task_input:
            with open(task_input["path"], "w") as fh:
                fh.write(task_input["content"])
            continue
        response = requests.get(task_input["url"], timeout=60)
        response.raise_for_status()
        with open(task_input["path"], "rb") as fh:
            if fh.read() != response.content:
                raise Exception(f"Galaxy sent other content for {task_input['path']}")
    [volume] = task["volumes"]
    before = _file_stamps(volume)
    for executor in task["executors"]:
        env = {**os.environ, **executor.get("env", {})}
        subprocess.run(executor["command"], cwd=executor["workdir"], env=env, check=True)
    uploaded = set()
    for output in task["outputs"]:
        for path, url in _output_files(output):
            with open(path, "rb") as fh:
                content = fh.read()
            os.unlink(path)
            requests.put(url, data=content, timeout=60).raise_for_status()
            uploaded.add(path)
    for path, stamp in _file_stamps(volume).items():
        if path not in uploaded and before.get(path) != stamp:
            os.unlink(path)


def _output_files(output: dict[str, Any]) -> list[tuple[str, str]]:
    """Each file of a TES output and the URL to upload it to."""
    if output["type"] == "FILE":
        return [(output["path"], output["url"])]
    url = urlsplit(output["url"])
    files = []
    for root, _, names in os.walk(output["path"]):
        for name in names:
            path = os.path.join(root, name)
            # Funnel escapes each segment of the path below the directory.
            rel_path = "/".join(quote(part, safe="") for part in os.path.relpath(path, output["path"]).split(os.sep))
            files.append((path, urlunsplit(url._replace(path=f"{url.path}/{rel_path}"))))
    return files


def _file_stamps(directory: str) -> dict[str, tuple[int, int]]:
    stamps = {}
    for root, _, names in os.walk(directory):
        for name in names:
            path = os.path.join(root, name)
            stat = os.lstat(path)
            stamps[path] = (stat.st_mtime_ns, stat.st_size)
    return stamps


class TesRunnerIntegrationInstance(integration_util.IntegrationInstance):
    """A Galaxy that runs every tool but uploads with the TES-native runner on a ``LocalTesServer``."""

    framework_tool_and_types = True
    tes_server: ClassVar[LocalTesServer]

    @classmethod
    def handle_galaxy_config_kwds(cls, config):
        super().handle_galaxy_config_kwds(config)
        cls.tes_server = LocalTesServer()
        job_conf = os.path.join(cls._test_driver.mkdtemp(), "tes_job_conf.yml")
        with open(job_conf, "w") as fh:
            fh.write(JOB_CONF_TEMPLATE.format(tes_url=cls.tes_server.url))
        config["job_config_file"] = job_conf
        # The runner's default galaxy_url, which task URLs point at.
        config["galaxy_infrastructure_url"] = "http://localhost:$GALAXY_WEB_PORT"
        # Tools without a container of their own get docker_default_container_id, without looking one up.
        config["container_resolvers"] = [{"type": "explicit"}]

    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        cls.tes_server.stop()


instance = integration_util.integration_module_instance(TesRunnerIntegrationInstance)

# An input dataset; a tool directory file and a from_work_dir output; discovered outputs.
test_tools = integration_util.integration_tool_runner(["cat1", "tool_directory_docker", "multi_output_assign_primary"])


def test_task_urls_carry_signed_tokens_not_the_job_key(instance):
    dataset_populator = DatasetPopulator(instance.galaxy_interactor)
    history_id = dataset_populator.new_history()
    run = dataset_populator.run_cat1(history_id)

    assert dataset_populator.get_history_dataset_content(history_id, dataset_id=run.output_id) == "1 2 3\n4 5 6\n"
    task = instance.tes_server.task_for_job(instance._app.security.decode_id(run.job_id))
    urls = [file["url"] for file in task["inputs"] + task["outputs"] if "url" in file]
    assert urls
    for url in urls:
        assert set(parse_qs(urlsplit(url).query)) == {"path", "job_token"}


def test_tool_exit_code_fails_the_job(instance):
    dataset_populator = DatasetPopulator(instance.galaxy_interactor)
    history_id = dataset_populator.new_history()
    exit_code_file = dataset_populator.new_dataset(history_id, content="3\n", wait=True)

    run = dataset_populator.run_tool(
        "exit_code_from_file", {"input": {"src": "hda", "id": exit_code_file["id"]}}, history_id
    )
    job_id = run["jobs"][0]["id"]
    dataset_populator.wait_for_job(job_id)

    job = dataset_populator.get_job_details(job_id, full=True).json()
    assert job["state"] == "error"
    assert job["exit_code"] == 3
