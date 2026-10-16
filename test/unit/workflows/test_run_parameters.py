import json
from typing import cast

import pytest

from galaxy import model
from galaxy.managers.context import ProvidesHistoryContext
from galaxy.model.unittest_utils.utils import random_email
from galaxy.tools.parameters.meta import expand_workflow_inputs
from galaxy.workflow.modules import populate_module_and_state
from galaxy.workflow.run_request import (
    _normalize_inputs,
    _normalize_step_parameters,
    workflow_run_config_to_request,
    WorkflowRunConfig,
)
from .workflow_support import (
    MockTrans,
    yaml_to_model,
)

STEP_ID_OFFSET = 4  # Offset a little so ids and order index are different.

NESTED_SUBWORKFLOW_YAML = """
steps:
  - type: data_input
    tool_inputs: {name: outer_input}
  - type: subworkflow
    subworkflow:
      steps:
        - type: data_input
          tool_inputs: {name: inner_input}
        - type: tool
          tool_id: random_lines1
        - type: subworkflow
          subworkflow:
            steps:
              - type: tool
                tool_id: random_lines1
"""


@pytest.mark.parametrize("legacy", [False, True])
def test_expand_scalar_parameter_inputs(legacy):
    values = [100, 0.1, False, None, "ND"]
    batch = {"batch": True, "values": values}
    if legacy:
        expansion = expand_workflow_inputs({"0": {"input": batch}})
        assert expansion.param_combinations == [{"0": {"input": value}} for value in values]
    else:
        expansion = expand_workflow_inputs({}, inputs={"0": batch})
        assert expansion.input_combinations == [{"0": value} for value in values]
    assert expansion.param_keys == [[] for _ in values]


def test_normalize_parameters_empty():
    normalized_params = __normalize_parameters_against_fixture({})
    assert normalized_params == {}


def test_normalize_parameters_by_tool():
    normalized_params = __normalize_parameters_against_fixture({"cat1": {"foo": "bar"}})
    # Tool specified parameters are expanded out.
    assert normalized_params[STEP_ID_OFFSET + 3] == {"foo": "bar"}
    assert normalized_params[STEP_ID_OFFSET + 4] == {"foo": "bar"}
    assert len(normalized_params.keys()) == 2


def test_step_parameters():
    normalized_params = __normalize_parameters_against_fixture({str(STEP_ID_OFFSET + 1): {"foo": "bar"}})
    assert normalized_params[STEP_ID_OFFSET + 1] == {"foo": "bar"}
    assert len(normalized_params.keys()) == 1


def test_step_parameters_legacy():
    normalized_params = __normalize_parameters_against_fixture(
        {str(STEP_ID_OFFSET + 1): {"param": "foo", "value": "bar"}}
    )
    assert normalized_params[STEP_ID_OFFSET + 1] == {"foo": "bar"}, normalized_params
    assert len(normalized_params.keys()) == 1


def _resolve_step_parameter_row(workflow: model.Workflow, name: str | None, value: str | None):
    invocation = model.WorkflowInvocation()
    invocation.workflow = workflow
    parameter = model.WorkflowRequestInputParameter(
        name=name, value=value, type=model.WorkflowRequestInputParameter.types.STEP_PARAMETERS
    )
    parameter.workflow_invocation = invocation
    return parameter.resolve_step_parameters()


def test_nested_subworkflow_step_parameters_round_trip():
    workflow = yaml_to_model(NESTED_SUBWORKFLOW_YAML)
    subworkflow_step = workflow.step_by_index(1)
    tool_step = subworkflow_step.subworkflow.step_by_index(1)
    nested_step = subworkflow_step.subworkflow.step_by_index(2)
    nested_tool_step = nested_step.subworkflow.step_by_index(0)
    by_index = {"1|num_lines": 2, "2|0|seed_source|seed": "moo"}

    normalized = _normalize_step_parameters(workflow.steps, {"1": by_index}, already_normalized=True)

    assert normalized == {
        subworkflow_step.id: {
            tool_step.id: {"num_lines": 2},
            nested_step.id: {nested_tool_step.id: {"seed_source|seed": "moo"}},
        }
    }
    # Stored as a JSON row, so inner step ids come back as strings.
    stored_value = json.dumps(normalized[subworkflow_step.id])
    assert _resolve_step_parameter_row(workflow, str(subworkflow_step.id), stored_value) == (
        subworkflow_step,
        by_index,
    )


def test_resolve_step_parameters_unknown_step():
    workflow = yaml_to_model(NESTED_SUBWORKFLOW_YAML)
    subworkflow_step = workflow.step_by_index(1)

    assert _resolve_step_parameter_row(workflow, "9999", json.dumps({"num_lines": 2})) is None
    assert (
        _resolve_step_parameter_row(workflow, str(subworkflow_step.id), json.dumps({"9999": {"num_lines": 2}})) is None
    )


def test_resolve_step_parameters_malformed_row():
    workflow = yaml_to_model(NESTED_SUBWORKFLOW_YAML)
    subworkflow_step_id = str(workflow.step_by_index(1).id)

    for name, value in [
        (None, json.dumps({"num_lines": 2})),
        (subworkflow_step_id, None),
        ("num_lines", json.dumps(2)),
        (subworkflow_step_id, json.dumps({"x": {"num_lines": 2}})),
        (subworkflow_step_id, "{not json"),
    ]:
        with pytest.raises(ValueError):
            _resolve_step_parameter_row(workflow, name, value)


def test_subworkflow_step_parameters_do_not_leak_on_step_id_order_index_collision():
    # Outer step id 1 is also the subworkflow step's order_index, its parameters must not leak into the subworkflow.
    trans = cast(ProvidesHistoryContext, MockTrans())
    workflow = yaml_to_model("""
steps:
  - type: data_input
    id: 1
    tool_inputs: {name: outer_input}
  - type: subworkflow
    id: 2
    subworkflow:
      steps:
        - type: data_input
          id: 3
          tool_inputs: {name: inner_input}
""")
    populate_module_and_state(trans, workflow, param_map={})
    run_config = WorkflowRunConfig(
        target_history=model.History(),
        replacement_dict={},
        inputs={},
        param_map={1: {"seed": "outer"}, 2: {3: {"seed": "inner"}}},
    )

    invocation = workflow_run_config_to_request(trans, run_config, workflow)

    subworkflow_invocation = invocation.subworkflow_invocations[0].subworkflow_invocation
    step_parameters = {
        parameter.name: json.loads(parameter.value)
        for parameter in subworkflow_invocation.input_parameters
        if parameter.type == model.WorkflowRequestInputParameter.types.STEP_PARAMETERS
    }
    assert step_parameters == {"3": {"seed": "inner"}}


def test_inputs_by_step_id():
    input1 = __new_input()
    input2 = __new_input()
    normalized_inputs = __normalize_inputs_against_fixture(
        {str(STEP_ID_OFFSET + 1): input1, str(STEP_ID_OFFSET + 2): input2}, inputs_by="step_id"
    )
    assert normalized_inputs[STEP_ID_OFFSET + 1]["content"] == input1["content"]
    assert normalized_inputs[STEP_ID_OFFSET + 2]["content"] == input2["content"]


def test_inputs_by_step_index():
    input1 = __new_input()
    input2 = __new_input()
    normalized_inputs = __normalize_inputs_against_fixture({str(0): input1, str(1): input2}, inputs_by="step_index")
    assert normalized_inputs[STEP_ID_OFFSET + 1]["content"] == input1["content"]
    assert normalized_inputs[STEP_ID_OFFSET + 2]["content"] == input2["content"]


def test_inputs_by_name():
    input1 = __new_input()
    input2 = __new_input()
    normalized_inputs = __normalize_inputs_against_fixture({"input1": input1, "input2": input2}, inputs_by="name")
    assert normalized_inputs[STEP_ID_OFFSET + 1]["content"] == input1["content"]
    assert normalized_inputs[STEP_ID_OFFSET + 2]["content"] == input2["content"]


def __normalize_parameters_against_fixture(params):
    trans = MockTrans()
    # Create a throw away workflow so step ids and order_index
    # are different for actual fixture.
    __workflow_fixure(trans)

    workflow = __workflow_fixure(trans)
    normalized_params = _normalize_step_parameters(workflow.steps, params, legacy=True)
    return normalized_params


def __normalize_inputs_against_fixture(inputs, inputs_by):
    trans = MockTrans()
    # Create a throw away workflow so step ids and order_index
    # are different for actual fixture.
    __workflow_fixure(trans)

    workflow = __workflow_fixure(trans)
    normalized_inputs = _normalize_inputs(workflow.steps, inputs, inputs_by)
    return normalized_inputs


def __new_input():
    return dict(content=model.HistoryDatasetAssociation())


def __workflow_fixure(trans):
    user = model.User(email=random_email(), password="pass")
    stored_workflow = model.StoredWorkflow()
    stored_workflow.user = user
    workflow = model.Workflow()
    workflow.stored_workflow = stored_workflow

    def add_step(**kwds):
        workflow_step = model.WorkflowStep()
        for key, value in kwds.items():
            setattr(workflow_step, key, value)
        workflow.steps.append(workflow_step)

    session = trans.app.model.context
    session.add(workflow)

    add_step(type="data_input", order_index=0, tool_inputs={"name": "input1"})
    add_step(type="data_input", order_index=1, tool_inputs={"name": "input2"})
    add_step(
        type="tool",
        tool_id="cat1",
        order_index=2,
    )
    add_step(
        type="tool",
        tool_id="cat1",
        order_index=4,
    )
    session.commit()
    # Expunge and reload to ensure step state is as expected from database.
    workflow_id = workflow.id
    session.expunge_all()

    return session.get(model.Workflow, workflow_id)
