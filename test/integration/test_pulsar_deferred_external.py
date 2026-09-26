"""Exploratory macOS Pulsar HTTP matrix with enforced storage isolation."""

import json
import os
import subprocess
import sys
import tempfile
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest
import yaml

from .test_pulsar_deferred_data import TEXT_CONTENT, _DeferredPulsarCases

SERVICE_SCRIPT = str(Path(__file__).with_name("deferred_pulsar_service.py"))
pytestmark = pytest.mark.skipif(
    sys.platform != "darwin" or os.environ.get("GALAXY_TEST_EXTERNAL_PULSAR") != "1",
    reason="Exploratory storage isolation matrix requires macOS and GALAXY_TEST_EXTERNAL_PULSAR=1",
)


class _ExternalPulsarCases(_DeferredPulsarCases):
    @classmethod
    def handle_galaxy_config_kwds(cls, config):
        super().handle_galaxy_config_kwds(config)
        cls.experiment_dir = Path(tempfile.mkdtemp(prefix="deferred_pulsar_external_", dir="/private/tmp"))
        forbidden = Path(cls._test_driver.galaxy_test_tmp_dir).resolve()
        probe = forbidden / "pulsar_isolation_probe.txt"
        probe.write_text("Galaxy-only data")
        cls.galaxy_pid = os.getpid()
        profile = cls.experiment_dir / "pulsar.sb"
        profile.write_text(f'(version 1)(allow default)(deny file-read* file-write* (subpath "{forbidden}"))')
        ready = cls.experiment_dir / "ready.json"
        settings = {
            "probe": str(probe),
            "ready": str(ready),
            "staging_directory": str(cls.experiment_dir / "staging"),
            "persistence_directory": str(cls.experiment_dir / "persisted"),
            "tool_dependency_dir": "none",
            "conda_auto_init": False,
            "conda_auto_install": False,
            "galaxy_home": str(Path(__file__).resolve().parents[2]),
            "managers": {"_default_": {"type": "queued_python", "galaxy_virtual_env": sys.prefix}},
        }
        settings_path = cls.experiment_dir / "service.json"
        settings_path.write_text(json.dumps(settings))
        cls.service_log = (cls.experiment_dir / "pulsar.log").open("w")
        service_env = os.environ.copy()
        service_env["PYTHONPATH"] = str(Path(settings["galaxy_home"]) / "lib")
        cls.service = subprocess.Popen(
            [
                "/usr/bin/sandbox-exec",
                "-f",
                str(profile),
                sys.executable,
                SERVICE_SCRIPT,
                str(settings_path),
            ],
            cwd=cls.experiment_dir,
            env=service_env,
            stdout=cls.service_log,
            stderr=subprocess.STDOUT,
        )
        for _ in range(100):
            if ready.exists():
                break
            if cls.service.poll() is not None:
                raise RuntimeError((cls.experiment_dir / "pulsar.log").read_text())
            time.sleep(0.1)
        assert ready.exists(), f"Pulsar failed to start: {cls.experiment_dir}"
        cls.ready = json.loads(ready.read_text())
        job_config = {
            "runners": {
                "local": {"load": "galaxy.jobs.runners.local:LocalJobRunner"},
                "pulsar": {"load": "galaxy.jobs.runners.pulsar:PulsarRESTJobRunner"},
            },
            "execution": {
                "default": "pulsar",
                "environments": {
                    "local": {"runner": "local"},
                    "pulsar": {
                        "runner": "pulsar",
                        "url": f'http://127.0.0.1:{cls.ready["port"]}/',
                        "remote_metadata": True,
                        "default_file_action": "transfer",
                    },
                },
            },
            "tools": [{"class": "local", "environment": "local"}],
        }
        job_config_path = cls.experiment_dir / "job_conf.yml"
        job_config_path.write_text(yaml.safe_dump(job_config))
        config["job_config_file"] = str(job_config_path)
        config["fetch_url_allowlist"] = ["127.0.0.1"]
        print(f"External Pulsar evidence: {cls.experiment_dir}", flush=True)

    @classmethod
    def tearDownClass(cls):
        try:
            super().tearDownClass()
        finally:
            cls.service.terminate()
            cls.service.wait(timeout=15)
            cls.service_log.close()

    def test_deferred_http_text(self):
        requests = []
        galaxy_pid = os.getpid()

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                # Keep the socket open while lsof identifies the process fetching it.
                port = self.client_address[1]
                connections = subprocess.check_output(
                    [
                        "/usr/sbin/lsof",
                        "-nP",
                        f"-iTCP:{port}",
                        "-sTCP:ESTABLISHED",
                        "-Fpn",
                    ],
                    text=True,
                )
                pid = None
                clients = []
                for line in connections.splitlines():
                    if line.startswith("p"):
                        pid = int(line[1:])
                    if line.startswith(f"n127.0.0.1:{port}->"):
                        clients.append(pid)
                assert len(clients) == 1, connections
                command = subprocess.check_output(
                    ["/bin/ps", "-p", str(clients[0]), "-o", "command="], text=True
                ).strip()
                requests.append({"client_pid": clients[0], "command": command, "path": self.path})
                self.send_response(200)
                self.send_header("Content-Type", "text/plain")
                self.send_header("Content-Length", str(len(TEXT_CONTENT)))
                self.end_headers()
                self.wfile.write(TEXT_CONTENT)

        source = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        thread = threading.Thread(target=source.serve_forever, daemon=True)
        thread.start()
        evidence = {
            "evaluation": self.tool_evaluation_strategy,
            "galaxy_pid": galaxy_pid,
            "pulsar_pid": self.service.pid,
            "job_id": None,
            "requests": requests,
            "isolation_probe": self.ready["isolation_probe"],
        }
        try:
            with self.dataset_populator.test_history() as history_id:
                uri = f"http://127.0.0.1:{source.server_port}/deferred.txt"
                dataset = self.dataset_populator.create_deferred_hda(history_id, uri=uri, ext="txt")
                assert dataset["state"] == "deferred", dataset
                assert not requests, requests
                job_id = self._run_cat(history_id, dataset, TEXT_CONTENT)
                evidence["job_id"] = job_id
                self._assert_galaxy_materialization(job_id, TEXT_CONTENT)
                assert requests, evidence
                if self.tool_evaluation_strategy == "local":
                    assert all(request["client_pid"] == galaxy_pid for request in requests), evidence
                else:
                    assert all(
                        request["client_pid"] != galaxy_pid and "remote_tool_eval" in request["command"]
                        for request in requests
                    ), evidence
        finally:
            source.shutdown()
            source.server_close()
            thread.join(timeout=5)
            # Retain download placement even when the subsequent tool execution fails.
            (self.experiment_dir / "http_evidence.json").write_text(json.dumps(evidence, indent=2))


class TestExternalPulsarLocalEvaluation(_ExternalPulsarCases):
    pass


class TestExternalPulsarRemoteEvaluation(_ExternalPulsarCases):
    tool_evaluation_strategy = "remote"
    metadata_strategy = "extended"
