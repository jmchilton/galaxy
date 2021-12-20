"""Workflow invocation model store tests.

Someday when the API tests can safely assume the target Galaxy has tasks enabled, this should be moved
into the API test suite.
"""
import json
import tarfile
from typing import Any, Dict

from galaxy_test.api.test_workflows import RunsWorkflowFixtures
from galaxy_test.base import api_asserts
from galaxy_test.base.populators import (
    DatasetPopulator,
    RunJobsSummary,
    skip_without_tool,
    WorkflowPopulator,
)
from galaxy_test.driver.integration_util import (
    IntegrationTestCase,
    setup_celery_includes,
    UsesCeleryTasks,
)


celery_includes = setup_celery_includes()


class WorkflowTasksIntegrationTestCase(IntegrationTestCase, UsesCeleryTasks, RunsWorkflowFixtures):

    framework_tool_and_types = True

    @classmethod
    def handle_galaxy_config_kwds(cls, config):
        cls.setup_celery_config(config)

    def setUp(self):
        super().setUp()
        self.dataset_populator = DatasetPopulator(self.galaxy_interactor)
        self.workflow_populator = WorkflowPopulator(self.galaxy_interactor)

    @skip_without_tool("cat1")
    def test_invocation_usage_targz(self):
        workflow_id, invocation = self._run_workflow_once_get_invocation("test_invocation_targz")
        invocation_id = invocation["id"]
        url = f"invocations/{invocation_id}.tar.gz"
        invocation_response = self._get(url)
        self._assert_status_code_is(invocation_response, 200)

        invocation_id = invocation["id"]
        url = f"invocations/{invocation_id}.bag.zip"
        invocation_response = self._get(url)
        self._assert_status_code_is(invocation_response, 200)

        url = f"invocations/{invocation_id}.bag.ofdonuts"
        invocation_response = self._get(url)
        self._assert_status_code_is(invocation_response, 400)

    @skip_without_tool("cat1")
    def test_export_import_invocation(self):
        workflow_id, invocation = self._run_workflow_once_get_invocation("test_invocation_targz_2")
        invocation_id = invocation["id"]
        self.workflow_populator.wait_for_workflow(workflow_id, invocation_id, invocation["history_id"])

        invocation_details = self.workflow_populator.get_invocation(invocation_id, step_details="true")
        invocation_steps = invocation_details["steps"]
        assert len(invocation_steps) == 3
        invocation_step0 = invocation_steps[0]
        assert invocation_step0["order_index"] == 0
        assert "output" in invocation_step0["outputs"]
        invocation_step1 = invocation_steps[1]
        assert invocation_step1["order_index"] == 1
        assert "output" in invocation_step1["outputs"]
        invocation_step2 = invocation_steps[2]
        assert invocation_step2["order_index"] == 2
        assert "out_file1" in invocation_step2["outputs"]

        self._print_invocation(invocation_id)
        temp_tar = self.workflow_populator.download_invocation_to_store(invocation_id)
        with tarfile.open(name=temp_tar) as tf:
            assert "invocation_attrs.txt" in tf.getnames()
            invocation_attrs_f = tf.extractfile("invocation_attrs.txt")
            assert invocation_attrs_f
            invocation_attrs = json.load(invocation_attrs_f)
            assert len(invocation_attrs) == 1

            assert "jobs_attrs.txt" in tf.getnames()
            job_attrs_f = tf.extractfile("jobs_attrs.txt")
            assert job_attrs_f
            job_attrs = json.load(job_attrs_f)
            assert len(job_attrs) == 3  # cat1, 2 uploads...

        with self.dataset_populator.test_history() as history_id:
            response = self.workflow_populator.create_invocation_from_store(history_id, store_path=temp_tar)
        invocation_details = self._assert_one_invocation_created_and_get_details(response)

        invocation_steps = invocation_details["steps"]
        for invocation_step in invocation_steps:
            assert invocation_step["state"] == "scheduled"
        self._print_invocation(invocation_details["id"])
        jobs = []
        for invocation_step in invocation_steps:
            jobs.extend(invocation_step.get("jobs", []))
        assert len(jobs) == 1

        inputs = invocation_details["inputs"]
        assert len(inputs) == 2
        assert "0" in inputs
        assert "1" in inputs
        assert inputs["0"]["src"] == "hda"
        assert inputs["1"]["src"] == "hda"
        assert inputs["0"]["label"] == "WorkflowInput1"
        assert inputs["1"]["label"] == "WorkflowInput2"

        assert "output" in invocation_steps[0]["outputs"]
        assert "output" in invocation_steps[1]["outputs"]
        assert "out_file1" in invocation_steps[2]["outputs"]

    def _print_invocation(self, invocation_id):
        invocation_details = self.workflow_populator.get_invocation(invocation_id, step_details="true")
        invocation_steps = invocation_details["steps"]
        for invocation_step in invocation_steps:
            print(invocation_step)

    def test_export_import_invocation_collection_input(self):
        with self.dataset_populator.test_history() as history_id:
            summary = self._run_workflow_with_output_collections(history_id)
            invocation_id = summary.invocation_id
            temp_tar = self.workflow_populator.download_invocation_to_store(invocation_id)

            with self.dataset_populator.test_history() as history_id:
                response = self.workflow_populator.create_invocation_from_store(history_id, store_path=temp_tar)

            invocation_details = self._assert_one_invocation_created_and_get_details(response)
            output_collections = invocation_details["output_collections"]
            assert len(output_collections) == 1
            assert "wf_output_1" in output_collections
            out = output_collections["wf_output_1"]
            assert out["src"] == "hdca"

            inputs = invocation_details["inputs"]
            assert inputs["0"]["src"] == "hdca"

            self._rerun_imported_workflow(summary, invocation_details)

    def _rerun_imported_workflow(self, summary: RunJobsSummary, create_response: Dict[str, Any]):
        workflow_id = create_response["workflow_id"]
        history_id = self.dataset_populator.new_history()
        new_workflow_request = summary.workflow_request.copy()
        new_workflow_request["history"] = f"hist_id={history_id}"
        invocation_response = self.workflow_populator.invoke_workflow_raw(workflow_id, new_workflow_request)
        invocation_response.raise_for_status()
        invocation_id = invocation_response.json()["id"]
        self.workflow_populator.wait_for_workflow(workflow_id, invocation_id, history_id, assert_ok=True)

    def test_export_import_invocation_with_input_as_output(self):
        with self.dataset_populator.test_history() as history_id:
            summary = self._run_workflow_with_inputs_as_outputs(history_id)
            invocation_id = summary.invocation_id
            invocation_details = self.workflow_populator.get_invocation(invocation_id, step_details="true")
            temp_tar = self.workflow_populator.download_invocation_to_store(invocation_id)

            with self.dataset_populator.test_history() as history_id:
                response = self.workflow_populator.create_invocation_from_store(history_id, store_path=temp_tar)

            invocation_details = self._assert_one_invocation_created_and_get_details(response)
            output_values = invocation_details["output_values"]
            assert len(output_values) == 1
            assert "wf_output_param" in output_values
            out = output_values["wf_output_param"]
            print(str(invocation_details))
            assert out == "A text variable"
            inputs = invocation_details["input_step_parameters"]
            assert "text_input" in inputs

            self._rerun_imported_workflow(summary, invocation_details)

    def _assert_one_invocation_created_and_get_details(self, response: Any) -> Dict[str, Any]:
        assert isinstance(response, list)
        assert len(response) == 1
        invocation = response[0]
        assert "state" in invocation
        assert invocation["state"] == "scheduled"
        imported_invocation_id = invocation["id"]

        invocation_details = self.workflow_populator.get_invocation(imported_invocation_id, step_details="true")
        api_asserts.assert_has_keys(invocation_details, "inputs", "steps", "workflow_id")
        return invocation_details
