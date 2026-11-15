"""Warning - this is hard to test.

This is a terrible API to test - the state of what is allowed is
highly dependent on the state of the job - which Galaxy typically
tries to get running and finish ASAP. Additionally, what is allowed
is very dependent on Galaxy internals about how the job working
directory is structured.

An ideal test would be to run Pulsar and Galaxy on different disk
and different servers and have them talk to each other - but this
still wouldn't test security stuff.

As a result this test is highly coupled with internals in a way most
integration tests avoid - but @jmchilton's fear of not touching this
API has gone too far.
"""

import http.client
import io
import os
import re
import tempfile
import threading
import time
import uuid
from collections.abc import (
    Callable,
    Iterator,
)
from contextlib import contextmanager
from dataclasses import (
    dataclass,
    replace,
)
from unittest.mock import patch
from urllib.parse import (
    quote,
    urlencode,
    urlsplit,
)

import requests
from sqlalchemy import (
    event,
    select,
)
from sqlalchemy.engine import Engine
from tusclient import client

from galaxy import model
from galaxy.job_execution.setup import JobWorkingDirectory
from galaxy.model.base import ensure_object_added_to_session
from galaxy.security.job_files_tokens import (
    JOB_FILES_DIRECTORY_WRITE,
    JOB_FILES_READ,
    job_files_token,
    JOB_FILES_WRITE,
    JobFilesScope,
)
from galaxy.webapps.galaxy.api.job_files import UPLOAD_STAGING_PREFIX
from galaxy_test.base import api_asserts
from galaxy_test.base.populators import (
    DatasetPopulator,
    wait_on,
)
from galaxy_test.driver import integration_util

SCRIPT_DIRECTORY = os.path.abspath(os.path.dirname(__file__))
SIMPLE_JOB_CONFIG_FILE = os.path.join(SCRIPT_DIRECTORY, "simple_job_conf.xml")

TEST_INPUT_TEXT = "test input content\n"
TEST_OUTPUT_TEXT = "some initial text data"
TEST_TUS_CHUNK_SIZE = 1024
UPLOAD_BOUNDARY = "jobfilesboundary"
LARGE_UPLOAD_CHUNK_SIZE = 1024 * 1024
LARGE_UPLOAD_CHUNKS = 8


@dataclass
class RunningJob:
    job: model.Job
    job_key: str
    files_url: str
    output_path: str
    output_extra_files_path: str
    working_directory: str


class TestJobFilesIntegration(integration_util.IntegrationTestCase):
    initialized = False
    dataset_populator: DatasetPopulator
    input_hda: model.HistoryDatasetAssociation
    nginx_upload_job_files_store: str

    @classmethod
    def handle_galaxy_config_kwds(cls, config):
        super().handle_galaxy_config_kwds(config)
        config["job_config_file"] = SIMPLE_JOB_CONFIG_FILE
        config["object_store_store_by"] = "uuid"
        config["server_name"] = "files"
        cls.nginx_upload_job_files_store = cls._test_driver.mkdtemp()
        config["nginx_upload_job_files_store"] = cls.nginx_upload_job_files_store
        cls.initialized = False

    def setUp(self):
        super().setUp()
        self.dataset_populator = DatasetPopulator(self.galaxy_interactor)
        sa_session = self.sa_session
        stmt = select(model.HistoryDatasetAssociation).order_by(model.HistoryDatasetAssociation.id)
        if not TestJobFilesIntegration.initialized:
            history_id = self.dataset_populator.new_history()
            assert len(sa_session.scalars(stmt).all()) == 0
            self.dataset_populator.new_dataset(history_id, content=TEST_INPUT_TEXT, wait=True)
            assert len(sa_session.scalars(stmt).all()) == 1
            TestJobFilesIntegration.initialized = True
        # The first HDA is the shared input that create_static_job_with_state uses by default.
        self.input_hda = sa_session.scalars(stmt).first()

    def test_read_by_state(self):
        job, _, _ = self.create_static_job_with_state("running")
        job_id, job_key = self._api_job_keys(job)
        data = {"path": self.input_hda.get_file_name(), "job_key": job_key}
        get_url = self._api_url(f"jobs/{job_id}/files", use_key=True)
        head_response = requests.head(get_url, params=data)
        api_asserts.assert_status_code_is_ok(head_response)
        assert head_response.text == ""
        assert head_response.headers["content-length"] == str(len(TEST_INPUT_TEXT))
        response = requests.get(get_url, params=data)
        api_asserts.assert_status_code_is_ok(response)
        assert response.text == TEST_INPUT_TEXT

        # set job state to finished and ensure the file is no longer
        # readable
        self._change_job_state(job, "ok")

        get_url = self._api_url(f"jobs/{job_id}/files", use_key=True)
        response = requests.get(get_url, params=data)
        _assert_insufficient_permissions(response)

    def test_read_fails_if_input_file_purged(self):
        history_id, input_hda = self._new_input_hda()
        job, _, _ = self.create_static_job_with_state("running", input_hda=input_hda)
        job_id, job_key = self._api_job_keys(job)
        input_file_path = input_hda.get_file_name()
        data = {"path": input_file_path, "job_key": job_key}
        get_url = self._api_url(f"jobs/{job_id}/files", use_key=True)
        head_response = requests.head(get_url, params=data)
        api_asserts.assert_status_code_is_ok(head_response)
        delete_response = self.dataset_populator.delete_dataset(
            history_id, content_id=self._app.security.encode_id(input_hda.id), purge=True, wait_for_purge=True
        )
        assert delete_response.status_code == 200
        # wait_for_purge sees the HDA as purged; the purge task removes the file after that.
        wait_on(lambda: None if os.path.exists(input_file_path) else True, "input file to be removed")
        response = requests.get(get_url, params=data)
        assert response.status_code == 400
        assert response.json()["err_msg"] == "Input dataset(s) for job have been purged."

    def test_read_fails_if_input_file_removed_before_dataset_marked_purged(self):
        # A purge commits the HDA as purged, removes the file, then commits the dataset as purged.
        # A request that arrives between the last two steps must still report a purged input.
        _, input_hda = self._new_input_hda()
        sa_session = self.sa_session
        job, _, _ = self.create_static_job_with_state("running", input_hda=input_hda)
        job_id, job_key = self._api_job_keys(job)
        input_file_path = input_hda.get_file_name()
        input_hda.deleted = True
        input_hda.purged = True
        sa_session.commit()
        os.remove(input_file_path)
        assert not input_hda.dataset.purged
        data = {"path": input_file_path, "job_key": job_key}
        get_url = self._api_url(f"jobs/{job_id}/files", use_key=True)
        response = requests.get(get_url, params=data)
        assert response.status_code == 400
        assert response.json()["err_msg"] == "Input dataset(s) for job have been purged."

    def test_read_missing_file(self):
        # Without inputs, so a missing dataset-named file can't be blamed on a purged input.
        job = self._running_job(with_input=False)
        for name in ["missing", "dataset_missing.dat"]:
            params = {"path": os.path.join(job.working_directory, name), "job_key": job.job_key}
            api_asserts.assert_status_code_is(requests.head(job.files_url, params=params), 404)
            response = requests.get(job.files_url, params=params)
            api_asserts.assert_status_code_is(response, 404)
            api_asserts.assert_error_code_is(response, 404001)

    def test_read_directory(self):
        job = self._running_job()
        response = requests.get(job.files_url, params={"path": job.working_directory, "job_key": job.job_key})
        api_asserts.assert_status_code_is(response, 400)
        api_asserts.assert_error_code_is(response, 400008)

    def test_read_range(self):
        job = self._running_job()
        path = os.path.join(job.working_directory, "ranged")
        _write_file(path, "0123456789")
        params = {"path": path, "job_key": job.job_key}
        response = requests.get(job.files_url, params=params, headers={"Range": "bytes=2-5"})
        api_asserts.assert_status_code_is(response, 206)
        assert response.text == "2345"
        assert response.headers["content-range"] == "bytes 2-5/10"

    def test_write_by_state(self):
        job = self._running_job()
        api_asserts.assert_status_code_is_ok(self._post_job_file(job, job.output_path, TEST_OUTPUT_TEXT))
        _assert_file_contents(job.output_path, TEST_OUTPUT_TEXT)

        work_dir_file = os.path.join(job.working_directory, "work")
        api_asserts.assert_status_code_is_ok(self._post_job_file(job, work_dir_file, TEST_OUTPUT_TEXT))
        _assert_file_contents(work_dir_file, TEST_OUTPUT_TEXT)

        # set job state to finished and ensure the file is no longer
        # writable
        self._change_job_state(job.job, "ok")
        _assert_insufficient_permissions(self._post_job_file(job, work_dir_file, TEST_OUTPUT_TEXT))

    def test_write_with_form_params(self):
        job = self._running_job()
        new_file_path_contents = set(os.listdir(self._app.config.new_file_path))
        response = self._post_job_file(job, job.output_path, TEST_OUTPUT_TEXT, form_auth=True)
        api_asserts.assert_status_code_is_ok(response)
        _assert_file_contents(job.output_path, TEST_OUTPUT_TEXT)
        work_dir_file = os.path.join(job.working_directory, "work")
        response = self._post_job_file(job, work_dir_file, TEST_OUTPUT_TEXT, form_auth=True)
        api_asserts.assert_status_code_is_ok(response)
        _assert_file_contents(work_dir_file, TEST_OUTPUT_TEXT)
        assert set(os.listdir(self._app.config.new_file_path)) == new_file_path_contents

    def test_write_with_tus(self):
        job = self._running_job()
        upload_url = self._api_url(f"job_files/resumable_upload?job_key={job.job_key}", use_key=False)
        my_client = client.TusClient(upload_url, headers={})
        t_file = tempfile.NamedTemporaryFile("w")
        t_file.write(TEST_OUTPUT_TEXT)
        t_file.flush()

        uploader = my_client.uploader(t_file.name, metadata={}, url_storage=None)
        uploader.chunk_size = TEST_TUS_CHUNK_SIZE
        uploader.upload()
        upload_session_url = uploader.url
        assert upload_session_url
        tus_session_id = upload_session_url.rsplit("/", 1)[1]  # type: ignore[unreachable]

        response = self._post_job_file(job, job.output_path, data={"session_id": tus_session_id})
        api_asserts.assert_status_code_is_ok(response)
        _assert_file_contents(job.output_path, TEST_OUTPUT_TEXT)

    def test_tus_hooks_accepts_hooks(self):
        response = requests.post(self._api_url("job_files/tus_hooks", use_key=False), json={"Type": "pre-create"})
        api_asserts.assert_status_code_is_ok(response)

    def test_write_with_nginx_upload_module(self):
        job = self._running_job()
        upload_path = os.path.join(self.nginx_upload_job_files_store, "nginx_upload")
        _write_file(upload_path, TEST_OUTPUT_TEXT)

        response = self._post_job_file(job, job.output_path, data={"__file_path": upload_path})
        api_asserts.assert_status_code_is_ok(response)
        assert not os.path.exists(upload_path)
        _assert_file_contents(job.output_path, TEST_OUTPUT_TEXT)

    def test_write_with_nginx_upload_module_rejects_path_outside_store(self):
        job = self._running_job()
        outside_path = os.path.join(self._test_driver.mkdtemp(), "outside")
        _write_file(outside_path, "not an upload")
        relative_outside_path = os.path.relpath(outside_path, self.nginx_upload_job_files_store)
        traversal_path = os.path.join(self.nginx_upload_job_files_store, relative_outside_path)
        assert traversal_path.startswith(self.nginx_upload_job_files_store)
        self._assert_nginx_upload_rejected(job, traversal_path, outside_path)

    def test_write_with_nginx_upload_module_rejects_relative_path(self):
        job = self._running_job()
        with tempfile.TemporaryDirectory(dir=os.getcwd()) as outside_dir:
            outside_path = os.path.join(outside_dir, "outside")
            _write_file(outside_path, "not an upload")
            relative_path = os.path.relpath(outside_path)
            assert not relative_path.startswith("..")
            self._assert_nginx_upload_rejected(job, relative_path, outside_path)

    def test_write_with_missing_upload_source(self):
        job = self._running_job()
        missing_nginx_path = os.path.join(self.nginx_upload_job_files_store, "missing")
        for data, err_msg in [
            ({"session_id": "missing-session"}, "No upload found for session id."),
            ({"__file_path": missing_nginx_path}, "File provided by nginx does not exist."),
        ]:
            response = self._post_job_file(job, job.output_path, data=data)
            api_asserts.assert_status_code_is(response, 400)
            api_asserts.assert_error_code_is(response, 400008)
            assert response.json()["err_msg"] == err_msg
        _assert_file_contents(job.output_path, "")

    def test_write_relative_path_rejected(self):
        job = self._running_job()
        relative_path = os.path.join(f"job_files_relative_{uuid.uuid4().hex}", "work")
        for path in [relative_path, "123"]:
            for form_auth in [False, True]:
                response = self._post_job_file(job, path, TEST_OUTPUT_TEXT, form_auth=form_auth)
                api_asserts.assert_status_code_is(response, 400)
                api_asserts.assert_error_message_contains(response, "absolute path")
        assert not os.path.exists(relative_path)

    def test_write_invalid_upload_sources_rejected(self):
        job = self._running_job()
        response = self._post_job_file(job, job.output_path, data={"session_id": "not/a-session"})
        api_asserts.assert_status_code_is(response, 400)
        api_asserts.assert_error_message_contains(response, "Invalid session id")

        upload_path = os.path.join(self.nginx_upload_job_files_store, "unconfigured")
        _write_file(upload_path, "not an upload")
        with patch.object(self._app.config, "nginx_upload_job_files_store", None):
            response = self._post_job_file(job, job.output_path, data={"__file_path": upload_path})
        api_asserts.assert_status_code_is(response, 403)
        api_asserts.assert_error_message_contains(response, "nginx_upload_module")
        _assert_file_contents(job.output_path, "")

    def test_write_without_file(self):
        job = self._running_job()
        response = requests.post(job.files_url, params={"path": job.output_path, "job_key": job.job_key})
        api_asserts.assert_status_code_is(response, 400)
        api_asserts.assert_error_code_is(response, 400007)
        _assert_file_contents(job.output_path, "")
        assert not _staging_dirs(os.path.dirname(job.output_path))

    def test_write_with_malformed_multipart(self):
        job = self._running_job()
        headers = {"Content-Type": f"multipart/form-data; boundary={UPLOAD_BOUNDARY}"}
        params = {"path": job.output_path, "job_key": job.job_key}
        response = requests.post(job.files_url, params=params, data=b"not multipart", headers=headers)
        api_asserts.assert_status_code_is(response, 400)
        api_asserts.assert_error_code_is(response, 400008)
        _assert_file_contents(job.output_path, "")
        assert not _staging_dirs(os.path.dirname(job.output_path))

    def test_unknown_job(self):
        job = self._running_job()
        missing_job_id = 2**31 - 1
        encoded_job_id = self._app.security.encode_id(missing_job_id)
        unknown_job = replace(
            job,
            files_url=self._api_url(f"jobs/{encoded_job_id}/files", use_key=False),
            job_key=self._app.security.encode_id(missing_job_id, kind="jobs_files"),
        )
        response = requests.get(unknown_job.files_url, params={"path": job.output_path, "job_key": unknown_job.job_key})
        api_asserts.assert_status_code_is(response, 404)
        api_asserts.assert_status_code_is(self._post_job_file(unknown_job, job.output_path, TEST_OUTPUT_TEXT), 404)

    def test_write_with_underscored_file_param(self):
        job = self._running_job()
        response = self._post_job_file(job, job.output_path, TEST_OUTPUT_TEXT, file_param="__file")
        api_asserts.assert_status_code_is_ok(response)
        _assert_file_contents(job.output_path, TEST_OUTPUT_TEXT)

    def test_write_with_query_params(self):
        job = self._running_job()
        response = self._post_job_file(job, job.output_path, TEST_OUTPUT_TEXT, params={"file_type": "output"})
        api_asserts.assert_status_code_is_ok(response)
        _assert_file_contents(job.output_path, TEST_OUTPUT_TEXT)

    def test_write_appends_to_tool_streams(self):
        job = self._running_job()
        for stream in ["tool_stdout", "tool_stderr"]:
            path = os.path.join(job.working_directory, "outputs", stream)
            for i in range(5):
                api_asserts.assert_status_code_is_ok(self._post_job_file(job, path, f"{stream} {i}\n"))
            _assert_file_contents(path, "".join(f"{stream} {i}\n" for i in range(5)))
        assert not _staging_dirs(job.working_directory)

    def test_write_replaces_other_files(self):
        job = self._running_job()
        path = os.path.join(job.working_directory, "work")
        for content in ["first", "second"]:
            api_asserts.assert_status_code_is_ok(self._post_job_file(job, path, content))
        _assert_file_contents(path, "second")

    def test_write_with_put(self):
        job = self._running_job()
        # TES servers such as Funnel send the raw body without a Content-Type.
        response = self._put_job_file(job, job.output_path, b"raw output bytes")
        api_asserts.assert_status_code_is_ok(response)
        _assert_file_contents(job.output_path, "raw output bytes")

        # Parent directories are created; tool streams are replaced, not appended to as by POST.
        tool_stdout = os.path.join(job.working_directory, "outputs", "tool_stdout")
        for content in (b"first", b"second"):
            api_asserts.assert_status_code_is_ok(self._put_job_file(job, tool_stdout, content))
        _assert_file_contents(tool_stdout, "second")
        assert not _staging_dirs(job.working_directory)

        self._change_job_state(job.job, "ok")
        _assert_insufficient_permissions(self._put_job_file(job, job.output_path, b"too late"))
        _assert_file_contents(job.output_path, "raw output bytes")

    def test_put_streams_large_body(self):
        job = self._running_job()
        path = os.path.join(job.working_directory, "large")
        staged_sizes: list[int] = []

        response = self._put_job_file(job, path, _large_raw_body(job.working_directory, staged_sizes.append))

        api_asserts.assert_status_code_is_ok(response)
        assert staged_sizes[0] >= (LARGE_UPLOAD_CHUNKS - 1) * LARGE_UPLOAD_CHUNK_SIZE
        assert os.path.getsize(path) == LARGE_UPLOAD_CHUNKS * LARGE_UPLOAD_CHUNK_SIZE + 3
        assert not _staging_dirs(job.working_directory)

    def test_put_write_protection(self):
        job = self._running_job()
        outside = tempfile.NamedTemporaryFile()
        _assert_insufficient_permissions(self._put_job_file(job, outside.name, b"x"))
        escape = os.path.join(job.working_directory, "..", "escape")
        _assert_insufficient_permissions(self._put_job_file(job, escape, b"x"))
        assert not os.path.exists(escape)
        work = os.path.join(job.working_directory, "work")
        _assert_insufficient_permissions(self._put_job_file(job, work, b"x", job_key="invalid"))
        assert not os.path.exists(work)
        assert not _staging_dirs(job.working_directory)
        relative = self._put_job_file(job, "relative/work", b"x")
        api_asserts.assert_status_code_is(relative, 400)
        for params in [{"path": work}, {"job_key": job.job_key}]:
            _assert_missing_attribute(requests.put(job.files_url, params=params, data=b"x"))

    def test_put_rejected_before_body_is_read(self):
        job = self._running_job()
        tool_working = os.path.join(job.working_directory, "working")
        path = os.path.join(tool_working, "work")
        finished = self._running_job(with_input=False)
        finished_path = os.path.join(finished.working_directory, "work")
        self._change_job_state(finished.job, "ok")
        for url, params in (
            # A read token.
            (job.files_url, {"path": path, "job_token": self._job_files_token(job, path, JOB_FILES_READ)}),
            # A finished job's write token.
            (
                finished.files_url,
                {"path": finished_path, "job_token": self._job_files_token(finished, finished_path, JOB_FILES_WRITE)},
            ),
            # A file write token for a directory.
            (
                f"{job.files_url}/work",
                {"path": tool_working, "job_token": self._job_files_token(job, tool_working, JOB_FILES_WRITE)},
            ),
            # An escape from the directory.
            (
                f"{job.files_url}/..%2Fescape",
                {
                    "path": tool_working,
                    "job_token": self._job_files_token(job, tool_working, JOB_FILES_DIRECTORY_WRITE),
                },
            ),
        ):
            # Announce a large body, send none of it and read the response: only a request
            # refused before its body is read gets an answer.
            status, body = self._send_headers_only("PUT", f"{url}?{urlencode(params)}", 100 * LARGE_UPLOAD_CHUNK_SIZE)
            assert status == 403, body
        assert not os.path.exists(path)
        assert not os.path.exists(finished_path)
        assert not os.path.exists(os.path.join(job.working_directory, "escape"))
        assert not _staging_dirs(job.working_directory)
        assert not _staging_dirs(finished.working_directory)

    def test_job_completes_during_put(self):
        for directory_route in (False, True):
            job = self._running_job(with_input=False)
            tool_working = os.path.join(job.working_directory, "working")
            path = os.path.join(tool_working, "large")

            def finish_job(staged_size: int, job: RunningJob = job) -> None:
                # The first authorization passed and the upload is being staged; now the job finishes.
                self._change_job_state(job.job, "ok")

            body = _large_raw_body(job.working_directory, finish_job)
            if directory_route:
                response = self._put_directory_file(job, tool_working, "large", body, job_key=job.job_key)
            else:
                response = self._put_job_file(job, path, body)
            _assert_insufficient_permissions(response)
            assert not os.path.exists(path)
            assert not _staging_dirs(job.working_directory)

    def test_signed_per_file_tokens(self):
        job = self._running_job()
        url = job.files_url
        # Not the shared input dataset: another test purges it.
        input_path = os.path.join(job.working_directory, "tool_script.sh")
        _write_file(input_path, TEST_INPUT_TEXT)
        output_path = job.output_path
        other_job = self._running_job(with_input=False)

        def token(path: str, scope: JobFilesScope, expires: int | None = None) -> str:
            return self._job_files_token(job, path, scope, expires)

        expired = int(time.time()) - 1

        # A read token reads its file, and nothing else.
        response = self._get_job_file(job, input_path, job_token=token(input_path, JOB_FILES_READ))
        api_asserts.assert_status_code_is_ok(response)
        assert response.text == TEST_INPUT_TEXT
        for auth in (
            {"job_token": token(input_path, JOB_FILES_WRITE)},
            {"job_token": token(output_path, JOB_FILES_READ)},
            {"job_token": token(input_path, JOB_FILES_READ, expired)},
            {"job_token": self._job_files_token(other_job, input_path, JOB_FILES_READ)},
            {"job_token": "garbage"},
            # A token, when given, is checked instead of the job key.
            {"job_token": "garbage", "job_key": job.job_key},
        ):
            _assert_insufficient_permissions(self._get_job_file(job, input_path, **auth))

        # A write token writes its file with PUT (Funnel, TESK) or multipart POST (tesp-api), and nothing else.
        response = self._put_job_file(job, output_path, b"put bytes", job_token=token(output_path, JOB_FILES_WRITE))
        api_asserts.assert_status_code_is_ok(response)
        _assert_file_contents(output_path, "put bytes")
        tool_stdout = os.path.join(job.working_directory, "outputs", "tool_stdout")
        response = requests.post(
            url,
            params={"path": tool_stdout, "job_token": token(tool_stdout, JOB_FILES_WRITE)},
            files={"file": io.StringIO("posted")},
        )
        api_asserts.assert_status_code_is_ok(response)
        _assert_file_contents(tool_stdout, "posted")
        other_file = os.path.join(job.working_directory, "other")
        for params in (
            {"path": output_path, "job_token": token(output_path, JOB_FILES_READ)},
            {"path": other_file, "job_token": token(output_path, JOB_FILES_WRITE)},
            {"path": output_path, "job_token": token(output_path, JOB_FILES_WRITE, expired)},
            {"path": output_path, "job_token": self._job_files_token(other_job, output_path, JOB_FILES_WRITE)},
        ):
            _assert_insufficient_permissions(requests.put(url, params=params, data=b"x"))
            _assert_insufficient_permissions(requests.post(url, params=params, files={"file": io.StringIO("x")}))
            _assert_insufficient_permissions(requests.post(url, data=params, files={"file": io.StringIO("x")}))
        _assert_file_contents(output_path, "put bytes")
        assert not os.path.exists(other_file)
        assert not _staging_dirs(job.working_directory)

        # A valid token doesn't widen the write locations.
        outside = tempfile.NamedTemporaryFile()
        response = self._put_job_file(job, outside.name, b"x", job_token=token(outside.name, JOB_FILES_WRITE))
        _assert_insufficient_permissions(response)

        # Tokens end with the job.
        self._change_job_state(job.job, "ok")
        response = self._get_job_file(job, input_path, job_token=token(input_path, JOB_FILES_READ))
        _assert_insufficient_permissions(response)

    def test_directory_put(self):
        """Funnel and TESK upload a TES DIRECTORY output as one PUT per file to ``<url path>/<relative path>?<query>``."""
        job = self._running_job()
        tool_working = os.path.join(job.working_directory, "working")

        def token(path: str, scope: JobFilesScope = JOB_FILES_DIRECTORY_WRITE) -> str:
            return self._job_files_token(job, path, scope)

        def put(rel_path: str, directory: str, data: bytes = b"x", **auth: str) -> requests.Response:
            return self._put_directory_file(job, directory, rel_path, data, **auth)

        # Funnel escapes each segment; TESK escapes everything but "/".
        response = put("sub/a%20b%2Bc.txt", tool_working, b"discovered", job_token=token(tool_working))
        api_asserts.assert_status_code_is_ok(response)
        _assert_file_contents(os.path.join(tool_working, "sub", "a b+c.txt"), "discovered")
        assert not _staging_dirs(job.working_directory)

        # An output's extra files directory, authorized by the job key, staged outside it.
        response = put("index.html", job.output_extra_files_path, b"page", job_key=job.job_key)
        api_asserts.assert_status_code_is_ok(response)
        _assert_file_contents(os.path.join(job.output_extra_files_path, "index.html"), "page")
        assert not _staging_dirs(job.output_extra_files_path)
        assert not _staging_dirs(os.path.dirname(job.output_path))

        outside = self._test_driver.mkdtemp()
        os.symlink(outside, os.path.join(tool_working, "link"))
        for rel_path, directory, auth in (
            # A file write token, a token for another directory, a bad key.
            ("x", tool_working, {"job_token": token(tool_working, JOB_FILES_WRITE)}),
            ("x", tool_working, {"job_token": token(job.working_directory)}),
            ("x", tool_working, {"job_key": "bad"}),
            # Escapes from the directory, though the job may write there.
            ("..%2Fescape", tool_working, {"job_token": token(tool_working)}),
            ("sub/..%2F..%2Fescape", tool_working, {"job_token": token(tool_working)}),
            (".", tool_working, {"job_token": token(tool_working)}),
            ("", tool_working, {"job_token": token(tool_working)}),
            (quote(os.path.join(outside, "x"), safe=""), tool_working, {"job_token": token(tool_working)}),
            ("link/x", tool_working, {"job_token": token(tool_working)}),
            # A directory outside the job's write locations, with a valid token for it.
            ("x", outside, {"job_token": token(outside)}),
        ):
            _assert_insufficient_permissions(put(rel_path, directory, b"x", **auth))
        assert not os.path.exists(os.path.join(job.working_directory, "escape"))
        assert not os.path.exists(os.path.join(tool_working, "x"))
        assert not os.listdir(outside)
        api_asserts.assert_status_code_is(put("x", "relative", job_key=job.job_key), 400)
        _assert_missing_attribute(put("x", tool_working))

        self._change_job_state(job.job, "ok")
        _assert_insufficient_permissions(put("late.txt", tool_working, job_token=token(tool_working)))

    def test_token_requests_load_only_the_job(self):
        """A TES task makes one request per staged file, below DIRECTORY outputs too: each loads only the job."""
        job = self._running_job()
        outputs = os.path.join(job.working_directory, "outputs")
        output = os.path.join(outputs, "dataset_1.dat")
        extra_files = os.path.join(outputs, "dataset_1_files")
        requests_by_name = {
            "GET": lambda: self._get_job_file(
                job,
                self.input_hda.get_file_name(),
                job_token=self._job_files_token(job, self.input_hda.get_file_name(), JOB_FILES_READ),
            ),
            "PUT": lambda: self._put_job_file(
                job, output, b"output", job_token=self._job_files_token(job, output, JOB_FILES_WRITE)
            ),
            "directory PUT": lambda: self._put_directory_file(
                job,
                extra_files,
                "sub/index.html",
                b"page",
                job_token=self._job_files_token(job, extra_files, JOB_FILES_DIRECTORY_WRITE),
            ),
        }
        for name, request in requests_by_name.items():
            with _request_statements(self._app.model.engine) as statements:
                api_asserts.assert_status_code_is_ok(request())
            assert len(statements) == 1 and re.search(r"\bFROM job\s", statements[0]), (name, statements)

    def test_write_and_read_path_with_percent_escapes(self):
        job = self._running_job()
        path = os.path.join(job.working_directory, "a%2Fb%20c")
        api_asserts.assert_status_code_is_ok(self._post_job_file(job, path, "escaped"))
        _assert_file_contents(path, "escaped")
        response = requests.get(job.files_url, params={"path": path, "job_key": job.job_key})
        api_asserts.assert_status_code_is_ok(response)
        assert response.text == "escaped"

    def test_write_streams_working_directory_upload(self):
        job = self._running_job()
        self._assert_upload_streamed(job, os.path.join(job.working_directory, "large"), job.working_directory)

    def test_write_streams_extra_file_upload_outside_extra_files_path(self):
        job = self._running_job()
        os.makedirs(job.output_extra_files_path)
        path = os.path.join(job.output_extra_files_path, "large")
        self._assert_upload_streamed(job, path, os.path.dirname(job.output_path))

    def test_rejected_upload_leaves_no_staged_files(self):
        job = self._running_job()
        path = os.path.join(job.working_directory, "work")
        outside_path = os.path.join(self._test_driver.mkdtemp(), "outside")
        new_file_path_contents = set(os.listdir(self._app.config.new_file_path))
        invalid_key_job = replace(job, job_key="invalid")
        _assert_insufficient_permissions(self._post_job_file(invalid_key_job, path, TEST_OUTPUT_TEXT))
        _assert_insufficient_permissions(self._post_job_file(job, outside_path, TEST_OUTPUT_TEXT))
        _assert_insufficient_permissions(self._post_job_file(invalid_key_job, path, TEST_OUTPUT_TEXT, form_auth=True))
        assert not _staging_dirs(job.working_directory)
        assert not _staging_dirs(os.path.dirname(outside_path))
        assert set(os.listdir(self._app.config.new_file_path)) == new_file_path_contents
        assert not os.path.exists(path)
        assert not os.path.exists(outside_path)

    def test_rejected_before_body_is_read(self):
        job = self._running_job()
        path = os.path.join(job.working_directory, "work")
        params = urlencode({"path": path, "job_key": "invalid"})
        # Announce a large body, send none of it and read the response: only a request
        # authorized before its body is read gets an answer.
        status, body = self._send_headers_only("POST", f"{job.files_url}?{params}", 100 * LARGE_UPLOAD_CHUNK_SIZE)
        assert status == 403, body
        assert not _staging_dirs(job.working_directory)
        assert not os.path.exists(path)

    def test_job_completes_during_upload(self):
        job = self._running_job()
        path = os.path.join(job.working_directory, "large")
        chunk = b"x" * LARGE_UPLOAD_CHUNK_SIZE

        def body():
            yield (
                f'--{UPLOAD_BOUNDARY}\r\nContent-Disposition: form-data; name="file"; filename="large"\r\n\r\n'
            ).encode()
            for _ in range(LARGE_UPLOAD_CHUNKS):
                yield chunk
            # The first authorization passed and the upload is being staged; now the job finishes.
            _wait_for_staged_upload(job.working_directory, (LARGE_UPLOAD_CHUNKS - 1) * LARGE_UPLOAD_CHUNK_SIZE)
            self._change_job_state(job.job, "ok")
            yield f"\r\n--{UPLOAD_BOUNDARY}--\r\n".encode()

        headers = {"Content-Type": f"multipart/form-data; boundary={UPLOAD_BOUNDARY}"}
        params = {"path": path, "job_key": job.job_key}
        response = requests.post(job.files_url, params=params, data=body(), headers=headers)
        _assert_insufficient_permissions(response)
        assert not os.path.exists(path)
        assert not _staging_dirs(job.working_directory)

    def test_client_disconnect_during_upload(self):
        job = self._running_job()
        path = os.path.join(job.working_directory, "large")
        params = urlencode({"path": path, "job_key": job.job_key})
        connection = self._start_request("POST", f"{job.files_url}?{params}", 100 * LARGE_UPLOAD_CHUNK_SIZE)
        connection.send(
            f'--{UPLOAD_BOUNDARY}\r\nContent-Disposition: form-data; name="file"; filename="large"\r\n\r\n'.encode()
        )
        connection.send(b"x" * LARGE_UPLOAD_CHUNK_SIZE)
        assert _wait_for_staging_dirs(job.working_directory, present=True)
        connection.close()
        assert _wait_for_staging_dirs(job.working_directory, present=False)
        assert not os.path.exists(path)

    def test_missing_params(self):
        job = self._running_job()
        for params in [{"path": job.output_path}, {"job_key": job.job_key}]:
            _assert_missing_attribute(requests.get(job.files_url, params=params))
            response = requests.post(job.files_url, params=params, files={"file": io.StringIO(TEST_OUTPUT_TEXT)})
            _assert_missing_attribute(response)
        _assert_file_contents(job.output_path, "")

    def test_write_protection(self):
        job, _, _ = self.create_static_job_with_state("running")
        job_id, job_key = self._api_job_keys(job)
        t_file = tempfile.NamedTemporaryFile()
        data = {"path": t_file.name, "job_key": job_key}
        file = io.StringIO("some initial text data")
        files = {"file": file}
        post_url = self._api_url(f"jobs/{job_id}/files", use_key=True)
        response = requests.post(post_url, data=data, files=files)
        _assert_insufficient_permissions(response)

    @property
    def sa_session(self):
        return self._app.model.session

    def _new_input_hda(self):
        """A job input of its own, for tests that purge it."""
        history_id = self.dataset_populator.new_history()
        hda_dict = self.dataset_populator.new_dataset(history_id, content=TEST_INPUT_TEXT, wait=True)
        input_hda = self.sa_session.get(model.HistoryDatasetAssociation, self._app.security.decode_id(hda_dict["id"]))
        assert input_hda
        return history_id, input_hda

    def create_static_job_with_state(self, state, with_input=True, input_hda=None):
        """Create a job with unknown handler so its state won't change."""
        sa_session = self.sa_session
        hda = input_hda or self.input_hda
        assert hda
        history = sa_session.scalars(select(model.History)).all()[0]
        assert history
        user = sa_session.scalars(select(model.User)).all()[0]
        assert user
        output_hda = model.HistoryDatasetAssociation(history=history, create_dataset=True, flush=False)
        output_hda.hid = 2
        sa_session.add(output_hda)
        sa_session.commit()
        job = model.Job()
        job.history = history
        ensure_object_added_to_session(job, object_in_session=history)
        job.user = user
        job.handler = "unknown-handler"
        job.state = state
        sa_session.add(job)
        if with_input:
            job.add_input_dataset("input1", hda)
        job.add_output_dataset("output1", output_hda)
        sa_session.commit()
        self._app.object_store.create(output_hda.dataset)
        working_directory = JobWorkingDirectory(job, self._app.object_store).create()
        return job, output_hda, working_directory

    def _running_job(self, with_input: bool = True) -> RunningJob:
        job, output_hda, working_directory = self.create_static_job_with_state("running", with_input=with_input)
        job_id, job_key = self._api_job_keys(job)
        output_path = self._app.object_store.get_filename(output_hda.dataset)
        assert output_path
        files_url = self._api_url(f"jobs/{job_id}/files", use_key=False)
        extra_files_path = output_hda.dataset.extra_files_path
        return RunningJob(job, job_key, files_url, output_path, extra_files_path, working_directory)

    def _post_job_file(
        self,
        job: RunningJob,
        path: str,
        content: str | None = None,
        data: dict[str, str] | None = None,
        params: dict[str, str] | None = None,
        file_param: str = "file",
        form_auth: bool = False,
    ) -> requests.Response:
        """Post like Pulsar - path and job_key as query params - unless ``form_auth``."""
        auth = {"path": path, "job_key": job.job_key}
        data = {**(data or {}), **(auth if form_auth else {})}
        params = {**(params or {}), **({} if form_auth else auth)}
        files = {file_param: io.StringIO(content)} if content is not None else None
        return requests.post(job.files_url, params=params, data=data, files=files)

    def _job_files_token(self, job: RunningJob, path: str, scope: JobFilesScope, expires: int | None = None) -> str:
        expires = int(time.time()) + 600 if expires is None else expires
        return job_files_token(self._app.security, job.job.id, path, scope, expires)

    def _get_job_file(self, job: RunningJob, path: str, **auth: str) -> requests.Response:
        return requests.get(job.files_url, params={"path": path, **auth})

    def _put_job_file(self, job: RunningJob, path: str, data, **auth: str) -> requests.Response:
        """PUT the raw body like Funnel and TESK - path and ``auth`` (default the job key) as query params."""
        return requests.put(job.files_url, params={"path": path, **(auth or {"job_key": job.job_key})}, data=data)

    def _put_directory_file(
        self, job: RunningJob, directory: str, rel_path: str, data, **auth: str
    ) -> requests.Response:
        """PUT the raw body like Funnel and TESK do for each file of a TES DIRECTORY output."""
        return requests.put(f"{job.files_url}/{rel_path}", params={"path": directory, **auth}, data=data)

    def _assert_upload_streamed(self, job: RunningJob, path: str, staging_parent: str):
        new_file_path_contents = set(os.listdir(self._app.config.new_file_path))
        chunk = b"x" * LARGE_UPLOAD_CHUNK_SIZE
        staged_sizes: list[int] = []
        extra_files_staging: list[list[str]] = []

        def body():
            yield (
                f'--{UPLOAD_BOUNDARY}\r\nContent-Disposition: form-data; name="file"; filename="large"\r\n\r\n'
            ).encode()
            for _ in range(LARGE_UPLOAD_CHUNKS):
                yield chunk
            staged_sizes.append(
                _wait_for_staged_upload(staging_parent, (LARGE_UPLOAD_CHUNKS - 1) * LARGE_UPLOAD_CHUNK_SIZE)
            )
            extra_files_staging.append(_staging_dirs(job.output_extra_files_path))
            yield f"\r\n--{UPLOAD_BOUNDARY}--\r\n".encode()

        headers = {"Content-Type": f"multipart/form-data; boundary={UPLOAD_BOUNDARY}"}
        params = {"path": path, "job_key": job.job_key}
        response = requests.post(job.files_url, params=params, data=body(), headers=headers)
        api_asserts.assert_status_code_is_ok(response)
        assert staged_sizes[0] >= (LARGE_UPLOAD_CHUNKS - 1) * LARGE_UPLOAD_CHUNK_SIZE
        assert extra_files_staging == [[]]
        assert os.path.getsize(path) == LARGE_UPLOAD_CHUNKS * LARGE_UPLOAD_CHUNK_SIZE
        assert not _staging_dirs(staging_parent)
        assert set(os.listdir(self._app.config.new_file_path)) == new_file_path_contents

    def _start_request(self, method: str, url: str, content_length: int) -> http.client.HTTPConnection:
        """Send the headers of a multipart POST or a raw PUT, leaving its body to the caller."""
        parts = urlsplit(url)
        connection = http.client.HTTPConnection(parts.netloc, timeout=30)
        connection.putrequest(method, f"{parts.path}?{parts.query}")
        if method == "POST":
            connection.putheader("Content-Type", f"multipart/form-data; boundary={UPLOAD_BOUNDARY}")
        connection.putheader("Content-Length", str(content_length))
        connection.endheaders()
        return connection

    def _send_headers_only(self, method: str, url: str, content_length: int) -> tuple[int, bytes]:
        connection = self._start_request(method, url, content_length)
        try:
            response = connection.getresponse()
            return response.status, response.read()
        finally:
            connection.close()

    def _assert_nginx_upload_rejected(self, job: RunningJob, file_path: str, outside_path: str):
        response = self._post_job_file(job, job.output_path, data={"__file_path": file_path})
        api_asserts.assert_status_code_is(response, 400)
        api_asserts.assert_error_code_is(response, 400008)
        assert os.path.exists(outside_path)
        _assert_file_contents(job.output_path, "")

    def _api_job_keys(self, job):
        job_id = self._app.security.encode_id(job.id)
        job_key = self._app.security.encode_id(job.id, kind="jobs_files")
        assert job_key
        return job_id, job_key

    def _change_job_state(self, job, state):
        job.state = state
        sa_session = self.sa_session
        sa_session.add(job)
        sa_session.commit()


@contextmanager
def _request_statements(engine: Engine) -> Iterator[list[str]]:
    """SQL statements that API requests, run in the server's AnyIO worker threads, execute meanwhile."""
    statements: list[str] = []

    def capture(_conn, _cursor, statement, _parameters, _context, _executemany) -> None:
        if threading.current_thread().name.startswith("AnyIO worker thread"):
            statements.append(statement)

    event.listen(engine, "before_cursor_execute", capture)
    try:
        yield statements
    finally:
        event.remove(engine, "before_cursor_execute", capture)


def _staging_dirs(directory):
    if not os.path.isdir(directory):
        return []
    return [name for name in os.listdir(directory) if name.startswith(UPLOAD_STAGING_PREFIX)]


def _wait_for_staging_dirs(directory, present, timeout=10):
    deadline = time.time() + timeout
    while time.time() < deadline:
        if bool(_staging_dirs(directory)) == present:
            return True
        time.sleep(0.05)
    return False


def _wait_for_staged_upload(directory, min_size, timeout=10):
    deadline = time.time() + timeout
    size = 0
    while time.time() < deadline:
        for staging_dir in _staging_dirs(directory):
            staging_path = os.path.join(directory, staging_dir)
            for name in os.listdir(staging_path):
                size = max(size, os.path.getsize(os.path.join(staging_path, name)))
        if size >= min_size:
            break
        time.sleep(0.05)
    return size


def _large_raw_body(staging_parent: str, on_staged: Callable[[int], None]) -> Iterator[bytes]:
    """LARGE_UPLOAD_CHUNKS chunks, then ``b"end"`` once most of them are staged below ``staging_parent``.

    ``on_staged`` gets the staged size before the end is sent.
    """
    chunk = b"x" * LARGE_UPLOAD_CHUNK_SIZE
    for _ in range(LARGE_UPLOAD_CHUNKS):
        yield chunk
    on_staged(_wait_for_staged_upload(staging_parent, (LARGE_UPLOAD_CHUNKS - 1) * LARGE_UPLOAD_CHUNK_SIZE))
    yield b"end"


def _assert_insufficient_permissions(response):
    api_asserts.assert_status_code_is(response, 403)
    api_asserts.assert_error_code_is(response, 403002)


def _assert_missing_attribute(response):
    api_asserts.assert_status_code_is(response, 400)
    api_asserts.assert_error_code_is(response, 400005)


def _write_file(path, content):
    with open(path, "w") as f:
        f.write(content)


def _assert_file_contents(path, expected):
    with open(path) as f:
        assert f.read() == expected
