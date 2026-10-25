"""Spike: step parameter overrides sent by the simple run form (exposed step params)."""

from galaxy_test.base.api_asserts import assert_error_message_contains
from galaxy_test.base.populators import skip_without_tool
from galaxy_test.base.workflow_fixtures import (
    WORKFLOW_EXPOSED_STEP_PARAMS,
    WORKFLOW_EXPOSED_STEP_PARAMS_DOUBLY_NESTED,
    WORKFLOW_EXPOSED_STEP_PARAMS_NESTED,
)
from .test_workflows import BaseWorkflowsApiTestCase


class TestWorkflowExposedStepParamsApi(BaseWorkflowsApiTestCase):
    def _invoke(self, history_id: str, yaml: str, parameters: dict, **extra):
        workflow_id = self.workflow_populator.upload_yaml_workflow(yaml)
        hda = self.dataset_populator.new_dataset(history_id, content="1\t2\t3\n", file_type="tabular", wait=True)
        request = {
            "history_id": history_id,
            "inputs": {"0": {"src": "hda", "id": hda["id"]}},
            "inputs_by": "step_index",
            "parameters": parameters,
            "parameters_normalized": True,
            **extra,
        }
        return workflow_id, self.workflow_populator.invoke_workflow_raw(workflow_id, request)

    def _echo(self, history_id: str, workflow_id: str, invocation_id: str) -> dict[str, str]:
        self.workflow_populator.wait_for_invocation_and_jobs(history_id, workflow_id, invocation_id)
        invocation = self.workflow_populator.get_invocation(invocation_id)
        content = self.dataset_populator.get_history_dataset_content(
            history_id, dataset_id=invocation["outputs"]["echo"]["id"]
        )
        return dict(line.split("=", 1) for line in content.splitlines() if line)

    @skip_without_tool("exposed_step_params")
    def test_nested_keys_apply(self, history_id):
        parameters = {
            "1": {
                "threshold": 0.9,
                "advanced|label": "tuned",
                "queries_1|column_name": "c9",
                "cond|min": 5,
            }
        }
        workflow_id, response = self._invoke(history_id, WORKFLOW_EXPOSED_STEP_PARAMS, parameters)
        self._assert_status_code_is(response, 200)
        echo = self._echo(history_id, workflow_id, response.json()["id"])
        assert echo["threshold"] == "0.9"
        assert echo["advanced.label"] == "tuned"
        assert echo["queries_0.column_name"] == "c1"
        assert echo["queries_1.column_name"] == "c9"
        assert echo["cond.min"] == "5"
        assert echo["mode"] == "fast"

    @skip_without_tool("exposed_step_params")
    def test_unknown_key_rejected(self, history_id):
        _, response = self._invoke(history_id, WORKFLOW_EXPOSED_STEP_PARAMS, {"1": {"thresold": 0.9}})
        self._assert_status_code_is(response, 400)
        assert_error_message_contains(response, "thresold")

    @skip_without_tool("exposed_step_params")
    def test_inactive_case_key_rejected(self, history_id):
        _, response = self._invoke(history_id, WORKFLOW_EXPOSED_STEP_PARAMS, {"1": {"cond|pattern": "x"}})
        self._assert_status_code_is(response, 400)
        assert_error_message_contains(response, "cond|pattern")

    @skip_without_tool("exposed_step_params")
    def test_missing_repeat_instance_rejected(self, history_id):
        _, response = self._invoke(history_id, WORKFLOW_EXPOSED_STEP_PARAMS, {"1": {"queries_5|column_name": "x"}})
        self._assert_status_code_is(response, 400)
        assert_error_message_contains(response, "queries_5|column_name")

    @skip_without_tool("exposed_step_params")
    def test_subworkflow_non_runtime_key_applies(self, history_id):
        parameters = {"1": {"1|threshold": 0.9, "1|cond|min": 7}}
        workflow_id, response = self._invoke(history_id, WORKFLOW_EXPOSED_STEP_PARAMS_NESTED, parameters)
        self._assert_status_code_is(response, 200)
        echo = self._echo(history_id, workflow_id, response.json()["id"])
        assert echo["threshold"] == "0.9"
        assert echo["cond.min"] == "7"

    @skip_without_tool("exposed_step_params")
    def test_subworkflow_unknown_inner_key_rejected(self, history_id):
        _, response = self._invoke(history_id, WORKFLOW_EXPOSED_STEP_PARAMS_NESTED, {"1": {"1|thresold": 0.9}})
        self._assert_status_code_is(response, 400)

    @skip_without_tool("exposed_step_params")
    def test_exposed_keys_round_trip(self, history_id):
        parameters = {"1": {"threshold": 0.9, "cond|min": 5}}
        exposed = ["1|threshold", "1|cond|min"]
        workflow_id, response = self._invoke(
            history_id, WORKFLOW_EXPOSED_STEP_PARAMS, parameters, exposed_step_parameters=exposed
        )
        self._assert_status_code_is(response, 200)
        invocation_id = response.json()["id"]
        self.workflow_populator.wait_for_invocation_and_jobs(history_id, workflow_id, invocation_id)
        request = self.workflow_populator.invocation_to_request(invocation_id)
        assert request["exposed_step_parameters"] == exposed
        assert request["parameters"] == {"1": {"threshold": 0.9, "cond|min": 5}}

    @skip_without_tool("exposed_step_params")
    def test_exposed_key_not_in_parameters_rejected(self, history_id):
        _, response = self._invoke(
            history_id, WORKFLOW_EXPOSED_STEP_PARAMS, {"1": {"threshold": 0.9}}, exposed_step_parameters=["1|mode"]
        )
        self._assert_status_code_is(response, 400)

    @skip_without_tool("exposed_step_params")
    def test_doubly_nested_subworkflow_key_applies(self, history_id):
        parameters = {"1": {"1|1|threshold": 0.9}}
        workflow_id, response = self._invoke(history_id, WORKFLOW_EXPOSED_STEP_PARAMS_DOUBLY_NESTED, parameters)
        self._assert_status_code_is(response, 200)
        assert self._echo(history_id, workflow_id, response.json()["id"])["threshold"] == "0.9"

    @skip_without_tool("exposed_step_params")
    def test_doubly_nested_unknown_key_rejected(self, history_id):
        _, response = self._invoke(history_id, WORKFLOW_EXPOSED_STEP_PARAMS_DOUBLY_NESTED, {"1": {"1|1|thresold": 0.9}})
        self._assert_status_code_is(response, 400)
