"""The endpoint a remote job runner uses to stage a job's inputs from the object store."""

import os
import time

import requests

from galaxy import model
from galaxy.security.staging_signer import input_url
from galaxy_test.base import api_asserts
from galaxy_test.base.populators import DatasetPopulator
from galaxy_test.driver import integration_util

SCRIPT_DIRECTORY = os.path.abspath(os.path.dirname(__file__))
SIMPLE_JOB_CONFIG_FILE = os.path.join(SCRIPT_DIRECTORY, "simple_job_conf.xml")
TEST_INPUT_TEXT = "test input content\n"


class TestJobObjectStagingIntegration(integration_util.IntegrationTestCase):
    dataset_populator: DatasetPopulator

    @classmethod
    def handle_galaxy_config_kwds(cls, config):
        super().handle_galaxy_config_kwds(config)
        config["job_config_file"] = SIMPLE_JOB_CONFIG_FILE
        config["object_store_store_by"] = "uuid"

    @property
    def sa_session(self):
        return self._app.model.session

    def setUp(self):
        super().setUp()
        self.dataset_populator = DatasetPopulator(self.galaxy_interactor)
        history_id = self.dataset_populator.new_history()
        hda_dict = self.dataset_populator.new_dataset(history_id, content=TEST_INPUT_TEXT, wait=True)
        input_hda = self.sa_session.get(model.HistoryDatasetAssociation, self._app.security.decode_id(hda_dict["id"]))
        assert input_hda is not None
        self.input_hda = input_hda

    def test_get_serves_the_input(self):
        job = self._running_job_with_input()
        response = requests.get(self._input_url(job))
        api_asserts.assert_status_code_is_ok(response)
        assert response.text == TEST_INPUT_TEXT

    def test_head_reports_the_size_without_a_body(self):
        job = self._running_job_with_input()
        response = requests.head(self._input_url(job))
        api_asserts.assert_status_code_is_ok(response)
        assert response.headers["content-length"] == str(len(TEST_INPUT_TEXT))
        assert response.text == ""

    def test_tampered_signature_is_refused(self):
        job = self._running_job_with_input()
        response = requests.get(self._input_url(job).replace("sig=", "sig=0"))
        api_asserts.assert_status_code_is(response, 403)

    def test_input_of_a_finished_job_is_refused(self):
        job = self._running_job_with_input()
        url = self._input_url(job)
        job.state = model.Job.states.OK
        self.sa_session.commit()
        response = requests.get(url)
        api_asserts.assert_status_code_is(response, 403)

    def _input_url(self, job):
        dataset = self.input_hda.dataset
        assert dataset is not None
        expires = int(time.time()) + 3600
        return input_url(self._app.security, self.url.rstrip("/"), job.id, "dataset", dataset.id, expires)

    def _running_job_with_input(self):
        return integration_util.create_static_job(
            self.sa_session, self.input_hda.history, model.Job.states.RUNNING, self.input_hda
        )
