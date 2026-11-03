"""API tests for the ``step_parameter_overrides`` field of workflow invocation requests."""

import json
import tarfile
from typing import Any

from requests import Response

from galaxy_test.base.api_asserts import assert_error_message_contains
from galaxy_test.base.populators import skip_without_tool
from galaxy_test.base.workflow_fixtures import (
    WORKFLOW_STEP_PARAMETER_OVERRIDES,
    WORKFLOW_STEP_PARAMETER_OVERRIDES_DOUBLY_NESTED,
    WORKFLOW_STEP_PARAMETER_OVERRIDES_NESTED,
)
from .test_workflows import BaseWorkflowsApiTestCase

# Step indexes in WORKFLOW_STEP_PARAMETER_OVERRIDES: 0 table, 1 threshold_param, 2 echo, 3 echo_connected.
ECHO = "2"


def _inner_step_parameters(subworkflow_step_parameters: dict[str, Any]) -> dict[str, Any]:
    """A subworkflow step's ``parameters`` in /request, one level deep, by parameter name.

    Independent of how /request keys them by inner step: nested by step, or as ``"<step>|<name>"``.
    """
    by_name: dict[str, Any] = {}
    for key, value in subworkflow_step_parameters.items():
        if isinstance(value, dict):
            by_name.update(value)
        else:
            by_name[key.split("|", 1)[1]] = value
    return by_name


class TestWorkflowStepParameterOverridesApi(BaseWorkflowsApiTestCase):
    def _table(self, history_id: str) -> str:
        return self.dataset_populator.new_dataset(history_id, content="1\t2\t3\n", file_type="tabular", wait=True)["id"]

    def _invoke(self, history_id: str, workflow_id: str, table_id: str | None = None, **request: Any):
        payload = {
            "history_id": history_id,
            "inputs": {"0": {"src": "hda", "id": table_id or self._table(history_id)}},
            "inputs_by": "step_index",
            **request,
        }
        return self.workflow_populator.invoke_workflow_raw(workflow_id, payload)

    def _invoke_ok(self, history_id: str, workflow_id: str, **request: Any) -> str:
        response = self._invoke(history_id, workflow_id, **request)
        self._assert_status_code_is(response, 200)
        return self._wait_for_invocation(history_id, workflow_id, response)

    def _wait_for_invocation(self, history_id: str, workflow_id: str, response: Response) -> str:
        invocation_id = response.json()["id"]
        self.workflow_populator.wait_for_invocation_and_jobs(history_id, workflow_id, invocation_id)
        return invocation_id

    def _subworkflow_request(self, invocation_id: str, step_index: int = 1) -> dict[str, Any]:
        """/request of the subworkflow invocation that ``invocation_id``'s step ``step_index`` ran."""
        invocation = self.workflow_populator.get_invocation(invocation_id)
        return self.workflow_populator.invocation_to_request(
            invocation["steps"][step_index]["subworkflow_invocation_id"]
        )

    def _echo(self, history_id: str, invocation_id: str, output: str = "echo") -> dict[str, str]:
        invocation = self.workflow_populator.get_invocation(invocation_id)
        content = self.dataset_populator.get_history_dataset_content(
            history_id, dataset_id=invocation["outputs"][output]["id"]
        )
        return dict(line.split("=", 1) for line in content.splitlines() if line)

    @skip_without_tool("echo_step_parameters")
    def test_overrides_merge_into_saved_tool_state(self, history_id):
        workflow_id = self.workflow_populator.upload_yaml_workflow(WORKFLOW_STEP_PARAMETER_OVERRIDES)
        overrides = {
            ECHO: {
                "threshold": 0.9,
                "flag": True,
                "advanced": {"label": "tuned"},
                "queries": [{}, {"column_name": "c9"}],
                "cond": {"min": 5},
            }
        }
        invocation_id = self._invoke_ok(history_id, workflow_id, step_parameter_overrides=overrides)
        echo = self._echo(history_id, invocation_id)
        assert echo["threshold"] == "0.9"
        assert echo["flag"] == "true"
        assert echo["advanced.label"] == "tuned"
        assert echo["queries_0.column_name"] == "c1"
        assert echo["queries_1.column_name"] == "c9"
        assert echo["cond.filter_type"] == "min"
        assert echo["cond.min"] == "5"
        assert echo["mode"] == "fast"

        request = self.workflow_populator.invocation_to_request(invocation_id)
        assert request["step_parameter_overrides"] == overrides
        assert request["parameters"] is None

    @skip_without_tool("echo_step_parameters")
    def test_overrides_switch_conditional_case(self, history_id):
        workflow_id = self.workflow_populator.upload_yaml_workflow(WORKFLOW_STEP_PARAMETER_OVERRIDES)
        overrides = {ECHO: {"cond": {"filter_type": "regex", "pattern": "^chr"}}}
        invocation_id = self._invoke_ok(history_id, workflow_id, step_parameter_overrides=overrides)
        echo = self._echo(history_id, invocation_id)
        assert echo["cond.filter_type"] == "regex"
        assert echo["cond.pattern"] == "^chr"

    @skip_without_tool("echo_step_parameters")
    def test_overrides_switch_conditional_case_uses_case_defaults(self, history_id):
        workflow_id = self.workflow_populator.upload_yaml_workflow(WORKFLOW_STEP_PARAMETER_OVERRIDES)
        invocation_id = self._invoke_ok(
            history_id, workflow_id, step_parameter_overrides={ECHO: {"cond": {"filter_type": "regex"}}}
        )
        echo = self._echo(history_id, invocation_id)
        assert echo["cond.filter_type"] == "regex"
        assert echo["cond.pattern"] == ".*"
        # The recorded overrides spell out the new case's defaults, as the job got them.
        request = self.workflow_populator.invocation_to_request(invocation_id)
        assert request["step_parameter_overrides"] == {ECHO: {"cond": {"filter_type": "regex", "pattern": ".*"}}}
        assert request["parameters"] is None

    @skip_without_tool("echo_step_parameters")
    def test_overrides_apply_on_top_of_parameters(self, history_id):
        workflow_id = self.workflow_populator.upload_yaml_workflow(WORKFLOW_STEP_PARAMETER_OVERRIDES)
        response = self._invoke(
            history_id,
            workflow_id,
            parameters={ECHO: {"threshold": 0.7, "mode": "careful", "cond|filter_type": "regex"}},
            parameters_normalized=True,
            step_parameter_overrides={ECHO: {"threshold": 0.9, "cond": {"pattern": "^chr"}}},
        )
        # Legacy parameters alone can't switch the case without setting its parameters - the override sets them.
        assert response.status_code == 200, response.text
        invocation_id = self._wait_for_invocation(history_id, workflow_id, response)
        echo = self._echo(history_id, invocation_id)
        assert echo["threshold"] == "0.9"
        assert echo["mode"] == "careful"
        assert echo["cond.pattern"] == "^chr"

        request = self.workflow_populator.invocation_to_request(invocation_id)
        assert request["step_parameter_overrides"] == {ECHO: {"threshold": 0.9, "cond": {"pattern": "^chr"}}}
        assert request["parameters"] == {ECHO: {"mode": "careful", "cond|filter_type": "regex"}}

    @skip_without_tool("echo_step_parameters")
    def test_overrides_apply_inside_subworkflow(self, history_id):
        workflow_id = self.workflow_populator.upload_yaml_workflow(WORKFLOW_STEP_PARAMETER_OVERRIDES_NESTED)
        overrides = {"1": {"1": {"threshold": 0.9, "queries": [{}, {"column_name": "c7"}], "cond": {"min": 7}}}}
        invocation_id = self._invoke_ok(history_id, workflow_id, step_parameter_overrides=overrides)
        echo = self._echo(history_id, invocation_id)
        assert echo["threshold"] == "0.9"
        assert echo["queries_1.column_name"] == "c7"
        assert echo["cond.min"] == "7"

        request = self.workflow_populator.invocation_to_request(invocation_id)
        assert request["step_parameter_overrides"] == overrides
        assert request["parameters"] is None

        subworkflow_request = self._subworkflow_request(invocation_id)
        assert subworkflow_request["step_parameter_overrides"] == overrides["1"]
        assert subworkflow_request["parameters"] is None

    @skip_without_tool("echo_step_parameters")
    def test_overrides_apply_two_subworkflow_levels_deep(self, history_id):
        workflow_id = self.workflow_populator.upload_yaml_workflow(WORKFLOW_STEP_PARAMETER_OVERRIDES_DOUBLY_NESTED)
        overrides = {"1": {"1": {"1": {"threshold": 0.9, "cond": {"filter_type": "regex", "pattern": "x"}}}}}
        invocation_id = self._invoke_ok(history_id, workflow_id, step_parameter_overrides=overrides)
        echo = self._echo(history_id, invocation_id)
        assert echo["threshold"] == "0.9"
        assert echo["cond.pattern"] == "x"
        request = self.workflow_populator.invocation_to_request(invocation_id)
        assert request["step_parameter_overrides"] == overrides
        assert request["parameters"] is None

    @skip_without_tool("echo_step_parameters")
    def test_overrides_apply_inside_subworkflow_on_top_of_parameters(self, history_id):
        workflow_id = self.workflow_populator.upload_yaml_workflow(WORKFLOW_STEP_PARAMETER_OVERRIDES_NESTED)
        invocation_id = self._invoke_ok(
            history_id,
            workflow_id,
            parameters={"1": {"1|threshold": 0.7, "1|mode": "careful"}},
            parameters_normalized=True,
            step_parameter_overrides={"1": {"1": {"threshold": 0.9}}},
        )
        echo = self._echo(history_id, invocation_id)
        assert echo["threshold"] == "0.9"
        assert echo["mode"] == "careful"

        # A parameter both fields set ran with the override's value, so /request reports it only there.
        request = self.workflow_populator.invocation_to_request(invocation_id)
        assert request["step_parameter_overrides"] == {"1": {"1": {"threshold": 0.9}}}
        assert list(request["parameters"]) == ["1"]
        assert _inner_step_parameters(request["parameters"]["1"]) == {"mode": "careful"}

        subworkflow_request = self._subworkflow_request(invocation_id)
        assert subworkflow_request["step_parameter_overrides"] == {"1": {"threshold": 0.9}}
        assert subworkflow_request["parameters"] == {"1": {"mode": "careful"}}

    @skip_without_tool("echo_step_parameters")
    def test_overrides_survive_invocation_export_and_import(self, history_id):
        workflow_id = self.workflow_populator.upload_yaml_workflow(WORKFLOW_STEP_PARAMETER_OVERRIDES)
        overrides = {ECHO: {"threshold": 0.9, "cond": {"min": 5}}}
        invocation_id = self._invoke_ok(history_id, workflow_id, step_parameter_overrides=overrides)
        store_path = self.workflow_populator.download_invocation_to_store(invocation_id)
        assert self._recorded_overrides(store_path) == overrides
        with self.dataset_populator.test_history() as import_history_id:
            imported = self.workflow_populator.create_invocation_from_store(
                history_id=import_history_id, store_path=store_path, model_store_format="tgz"
            )
            # /request of an imported invocation needs its step parameter rows re-keyed to the
            # imported workflow's steps (#24175), so check the imported request rows by re-exporting.
            reexported_path = self.workflow_populator.download_invocation_to_store(imported[0]["id"])
            assert self._recorded_overrides(reexported_path) == overrides

    def _recorded_overrides(self, store_path: str) -> Any:
        with tarfile.open(store_path) as store:
            member = next(m for m in store.getmembers() if m.name.endswith("invocation_attrs.txt"))
            extracted = store.extractfile(member)
            assert extracted
            (invocation_attrs,) = json.load(extracted)
        rows = [
            row
            for row in invocation_attrs["input_parameters"]
            if row["type"] == "meta" and row["name"] == "step_parameter_overrides"
        ]
        assert len(rows) == 1
        return json.loads(rows[0]["value"])

    @skip_without_tool("echo_step_parameters")
    def test_invalid_overrides_rejected(self, history_id):
        workflow_id = self.workflow_populator.upload_yaml_workflow(WORKFLOW_STEP_PARAMETER_OVERRIDES)
        table_id = self._table(history_id)
        cases: list[tuple[dict, str]] = [
            ({"7": {"threshold": 0.9}}, "'7': no step with this index"),
            ({"0": {"value": 1}}, "data_input step takes no parameter overrides"),
            ({ECHO: {"thresold": 0.9}}, "'2/thresold': unknown parameter"),
            ({ECHO: {"cond": {"pattern": "x"}}}, "'2/cond/pattern': not in the active case 'min'"),
            ({ECHO: {"cond": {"filter_type": "nope"}}}, "'2/cond/filter_type'"),
            ({ECHO: {"cond": {"__current_case__": 1}}}, "'2/cond/__current_case__': not a tool parameter"),
            ({ECHO: {"queries": [{}, {}, {"column_name": "x"}]}}, "overrides can't add instances"),
            ({ECHO: {"queries": {"column_name": "x"}}}, "a repeat takes a list of objects"),
            ({ECHO: {"advanced": "x"}}, "a section takes an object"),
            ({ECHO: {"input1": {"src": "hda", "id": table_id}}}, "data and collection parameters"),
            ({ECHO: {"threshold": {"__class__": "Batch", "values": [0.1, 0.2]}}}, "batch values are not supported"),
            ({ECHO: {"threshold": {"batch": True, "values": [0.1, 0.2]}}}, "batch values are not supported"),
            ({ECHO: {"__POST_JOB_ACTIONS__": {}}}, "post-job actions"),
            ({"3": {"threshold": 0.9}}, "connected to another step's output"),
        ]
        for overrides, message in cases:
            response = self._invoke(history_id, workflow_id, table_id, step_parameter_overrides=overrides)
            assert response.status_code == 400, f"{overrides}: {response.status_code} {response.text}"
            assert_error_message_contains(response, message)

        # Values are checked like legacy step parameters, when the step's runtime state is computed. Errors are
        # keyed by step index, then by the parameter's flat name.
        response = self._invoke(
            history_id,
            workflow_id,
            table_id,
            step_parameter_overrides={ECHO: {"threshold": "high", "advanced": {"label": "Tuned"}}},
        )
        self._assert_status_code_is(response, 400)
        err_data = response.json()["err_data"]
        assert list(err_data) == [ECHO], err_data
        assert set(err_data[ECHO]) == {"threshold", "advanced|label"}, err_data
        assert "Run labels are lowercase" in err_data[ECHO]["advanced|label"]

    @skip_without_tool("echo_step_parameters")
    def test_invalid_subworkflow_overrides_rejected(self, history_id):
        workflow_id = self.workflow_populator.upload_yaml_workflow(WORKFLOW_STEP_PARAMETER_OVERRIDES_DOUBLY_NESTED)
        table_id = self._table(history_id)
        cases: list[tuple[dict, str]] = [
            ({"1": {"5": {"threshold": 0.9}}}, "'1/5': no step with this index"),
            ({"1": {"1": {"1": {"thresold": 0.9}}}}, "'1/1/1/thresold': unknown parameter"),
            ({"1": {"1": {"1": {"cond": {"pattern": "x"}}}}}, "'1/1/1/cond/pattern': not in the active case"),
            ({"1": {"1": {"0": {"x": 1}}}}, "'1/1/0': a data_input step"),
        ]
        for overrides, message in cases:
            response = self._invoke(history_id, workflow_id, table_id, step_parameter_overrides=overrides)
            assert response.status_code == 400, f"{overrides}: {response.status_code} {response.text}"
            assert_error_message_contains(response, message)

        # An inner step's value errors are nested under the subworkflow steps it is in, as its overrides are.
        response = self._invoke(
            history_id,
            workflow_id,
            table_id,
            step_parameter_overrides={"1": {"1": {"1": {"threshold": "high", "cond": {"min": "x"}}}}},
        )
        self._assert_status_code_is(response, 400)
        err_data = response.json()["err_data"]
        assert list(err_data) == ["1"], err_data
        assert list(err_data["1"]) == ["1"], err_data
        assert set(err_data["1"]["1"]["1"]) == {"threshold", "cond|min"}, err_data

    @skip_without_tool("echo_step_parameters")
    def test_run_form_lists_subworkflow_tool_steps(self, history_id):
        workflow_id = self.workflow_populator.upload_yaml_workflow(WORKFLOW_STEP_PARAMETER_OVERRIDES_DOUBLY_NESTED)
        run_form = self.workflow_populator.download_workflow(workflow_id, style="run", history_id=history_id)
        outer = run_form["steps"][1]
        assert outer["step_type"] == "subworkflow"
        assert "subworkflow_steps" in outer, outer
        (nested,) = outer["subworkflow_steps"]
        assert (nested["step_type"], nested["step_index"]) == ("subworkflow", 1)
        (echo,) = nested["subworkflow_steps"]
        assert (echo["step_type"], echo["step_index"], echo["step_name"]) == ("tool", 1, "Echo step parameters")
        inputs = {input["name"]: input for input in echo["inputs"]}
        assert inputs["threshold"]["value"] == "0.5"
        assert inputs["cond"]["test_param"]["value"] == "min"
