"""Embedded Pulsar matrix for deferred inputs and remote tool evaluation."""

import base64
import os
from pathlib import Path

from sqlalchemy import select

from galaxy import model
from galaxy.job_execution.setup import JobWorkingDirectory
from galaxy_test.base.populators import DatasetPopulator
from galaxy_test.driver import integration_util

SCRIPT_DIRECTORY = os.path.abspath(os.path.dirname(__file__))
JOB_CONFIG_FILE = os.path.join(SCRIPT_DIRECTORY, "embedded_pulsar_deferred_job_conf.yml")
TEXT_CONTENT = b"deferred Pulsar input\n"


class _DeferredPulsarCases(integration_util.IntegrationTestCase):
    dataset_populator: DatasetPopulator
    framework_tool_and_types = True
    tool_evaluation_strategy = "local"
    metadata_strategy = "directory"

    def setUp(self) -> None:
        super().setUp()
        self.dataset_populator = DatasetPopulator(self.galaxy_interactor)

    @classmethod
    def handle_galaxy_config_kwds(cls, config) -> None:
        super().handle_galaxy_config_kwds(config)
        config["job_config_file"] = JOB_CONFIG_FILE
        config["enable_celery_tasks"] = False
        config["cleanup_job"] = "never"
        config["object_store_store_by"] = "uuid"
        config["metadata_strategy"] = cls.metadata_strategy
        config["tool_evaluation_strategy"] = cls.tool_evaluation_strategy

    def _run_cat(self, history_id: str, dataset: dict, expected: bytes) -> str:
        inputs = {"input1": {"src": "hda", "id": dataset["id"]}}
        response = self.dataset_populator.run_tool("cat1", inputs=inputs, history_id=history_id)
        job_id = response["jobs"][0]["id"]
        self.dataset_populator.wait_for_job(job_id, assert_ok=True)
        output_id = response["outputs"][0]["id"]
        actual = self.dataset_populator.get_history_dataset_content(
            history_id, dataset_id=output_id, type="bytes", raw=True
        )
        assert actual == expected
        return job_id

    def _assert_galaxy_materialization(self, job_id: str, expected: bytes) -> None:
        decoded_job_id = self._app.security.decode_id(job_id)
        job = self._app.model.session.scalars(select(model.Job).filter_by(id=decoded_job_id)).one()
        job_directory = JobWorkingDirectory(job, self._app.object_store).resolve()
        galaxy_inputs = list((Path(job_directory) / "inputs").glob("dataset_*.dat"))
        if self.tool_evaluation_strategy == "local":
            assert len(galaxy_inputs) == 1, galaxy_inputs
            assert galaxy_inputs[0].read_bytes() == expected
        else:
            assert not galaxy_inputs, galaxy_inputs

    def _deferred_dataset(self, history_id: str, content: bytes, ext: str) -> dict:
        uri = f"base64://{base64.b64encode(content).decode('ascii')}"
        dataset = self.dataset_populator.create_deferred_hda(history_id, uri=uri, ext=ext)
        assert dataset["state"] == "deferred", dataset
        return dataset

    def test_ordinary_text(self) -> None:
        with self.dataset_populator.test_history() as history_id:
            dataset = self.dataset_populator.new_dataset(
                history_id, content=TEXT_CONTENT.decode(), file_type="txt", wait=True
            )
            self._run_cat(history_id, dataset, TEXT_CONTENT)

    def test_deferred_text(self) -> None:
        with self.dataset_populator.test_history() as history_id:
            dataset = self._deferred_dataset(history_id, TEXT_CONTENT, "txt")
            job_id = self._run_cat(history_id, dataset, TEXT_CONTENT)
            self._assert_galaxy_materialization(job_id, TEXT_CONTENT)

    def test_deferred_bam(self) -> None:
        with open(self.test_data_resolver.get_filename("1.bam"), "rb") as bam_file:
            content = bam_file.read()
        with self.dataset_populator.test_history() as history_id:
            dataset = self._deferred_dataset(history_id, content, "bam")
            job_id = self._run_cat(history_id, dataset, content)
            self._assert_galaxy_materialization(job_id, content)


class TestDeferredPulsarLocalEvaluation(_DeferredPulsarCases):
    """Galaxy evaluates and materializes before Pulsar staging."""


class TestDeferredPulsarRemoteEvaluation(_DeferredPulsarCases):
    """Pulsar runs Galaxy's remote tool evaluator after staging."""

    tool_evaluation_strategy = "remote"
    metadata_strategy = "extended"
