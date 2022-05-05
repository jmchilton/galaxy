"""Workflow invocation model store tests.

Someday when the API tests can safely assume the target Galaxy has tasks enabled, this should be moved
into the API test suite.
"""
from typing import (
    Any,
    Dict,
)

from galaxy_test.api.test_workflows import RunsWorkflowFixtures
from galaxy_test.base import api_asserts
from galaxy_test.base.populators import (
    DatasetPopulator,
    RunJobsSummary,
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

    def test_export_import_invocation_collection_input(self):
        with self.dataset_populator.test_history() as history_id:
            summary = self._run_workflow_with_output_collections(history_id)
            invocation_details = self._export_and_import_worklflow_invocation(summary)
            output_collections = invocation_details["output_collections"]
            assert len(output_collections) == 1
            assert "wf_output_1" in output_collections
            out = output_collections["wf_output_1"]
            assert out["src"] == "hdca"

            inputs = invocation_details["inputs"]
            assert inputs["0"]["src"] == "hdca"

            self._rerun_imported_workflow(summary, invocation_details)

    def test_export_import_invocation_with_input_as_output(self):
        with self.dataset_populator.test_history() as history_id:
            summary = self._run_workflow_with_inputs_as_outputs(history_id)
            invocation_details = self._export_and_import_worklflow_invocation(summary)
            output_values = invocation_details["output_values"]
            assert len(output_values) == 1
            assert "wf_output_param" in output_values
            out = output_values["wf_output_param"]
            assert out == "A text variable"
            inputs = invocation_details["input_step_parameters"]
            assert "text_input" in inputs

            self._rerun_imported_workflow(summary, invocation_details)

    def test_export_import_invocation_with_step_parameter(self):
        # Run this to ensure order indices are preserved.
        with self.dataset_populator.test_history() as history_id:
            summary = self._run_workflow_with_runtime_data_column_parameter(history_id)
            invocation_details = self._export_and_import_worklflow_invocation(summary)
            self._rerun_imported_workflow(summary, invocation_details)

    def _export_and_import_worklflow_invocation(self, summary: RunJobsSummary) -> Dict[str, Any]:
        invocation_id = summary.invocation_id
        temp_tar = self.workflow_populator.download_invocation_to_store(invocation_id)

        with self.dataset_populator.test_history() as history_id:
            response = self.workflow_populator.create_invocation_from_store(history_id, store_path=temp_tar)

        imported_invocation_details = self._assert_one_invocation_created_and_get_details(response)
        return imported_invocation_details

    def _rerun_imported_workflow(self, summary: RunJobsSummary, create_response: Dict[str, Any]):
        workflow_id = create_response["workflow_id"]
        history_id = self.dataset_populator.new_history()
        new_workflow_request = summary.workflow_request.copy()
        new_workflow_request["history"] = f"hist_id={history_id}"
        invocation_response = self.workflow_populator.invoke_workflow_raw(workflow_id, new_workflow_request)
        invocation_response.raise_for_status()
        invocation_id = invocation_response.json()["id"]
        self.workflow_populator.wait_for_workflow(workflow_id, invocation_id, history_id, assert_ok=True)

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