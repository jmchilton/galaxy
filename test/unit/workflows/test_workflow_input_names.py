from typing import cast

import pytest

from galaxy import (
    exceptions,
    model,
)
from galaxy.managers.context import ProvidesHistoryContext
from galaxy.managers.workflows import (
    _workflow_input_name_upgrades,
    WorkflowContentsManager,
    WorkflowUpdateOptions,
)
from .workflow_support import (
    MockTrans,
    yaml_to_model,
)

StepSpec = tuple[str, str | None] | tuple[str, str | None, str]


def _workflow_with_steps(*steps: StepSpec) -> model.Workflow:
    """Build a workflow from (step_type, label[, legacy_tool_state_name]) tuples."""
    workflow = model.Workflow()
    workflow.name = "workflow input name test"
    workflow.steps = []
    for order_index, step_spec in enumerate(steps):
        step_type, label = step_spec[0], step_spec[1]
        legacy_name = step_spec[2] if len(step_spec) > 2 else None
        step = model.WorkflowStep()
        step.order_index = order_index
        step.type = step_type
        step.label = label
        step.tool_inputs = {"name": legacy_name} if legacy_name else {}
        workflow.steps.append(step)
    return workflow


def test_workflow_input_name_upgrades_avoid_label_collisions():
    workflow = _workflow_with_steps(
        ("data_input", "sample|reads"),
        ("tool", "sample_reads"),
        ("data_collection_input", "paired|reads"),
    )

    assert _workflow_input_name_upgrades(workflow) == {
        0: ("sample|reads", "sample_reads_2"),
        2: ("paired|reads", "paired_reads"),
    }


def test_workflow_input_name_upgrades_consider_labels_still_in_tool_state():
    workflow = _workflow_with_steps(
        ("data_input", None, "sample|reads"),
        ("data_input", None, "sample_reads"),
        ("data_input", None, "paired|reads"),
    )

    assert _workflow_input_name_upgrades(workflow) == {
        0: ("sample|reads", "sample_reads_2"),
        2: ("paired|reads", "paired_reads"),
    }


def test_editor_serialization_upgrades_input_name_still_in_tool_state():
    workflow = _workflow_with_steps(("data_input", None, "sample|reads"))
    trans = MockTrans()
    manager = WorkflowContentsManager(trans.app, trans.app.trs_proxy)

    editor_workflow = manager._workflow_to_dict_editor(
        cast(ProvidesHistoryContext, trans), None, workflow, tooltip=False
    )

    assert editor_workflow["steps"][0]["label"] == "sample_reads"
    assert "workflow_input_name" in editor_workflow["upgrade_messages"][0]


def test_step_dict_validation_rejects_input_name_still_in_tool_state():
    trans = MockTrans()
    manager = WorkflowContentsManager(trans.app, trans.app.trs_proxy)
    data = {"steps": {"0": {"type": "data_input", "tool_state": '{"name": "sample|reads"}'}}}

    with pytest.raises(exceptions.ObjectAttributeInvalidException) as exc_info:
        list(manager._WorkflowContentsManager__walk_step_dicts(data))  # type: ignore[attr-defined]

    assert "sample|reads" in str(exc_info.value)


def test_editor_serialization_upgrades_legacy_workflow_input_name():
    workflow = _workflow_with_steps(("data_input", "sample|reads"))
    trans = MockTrans()
    manager = WorkflowContentsManager(trans.app, trans.app.trs_proxy)

    editor_workflow = manager._workflow_to_dict_editor(
        cast(ProvidesHistoryContext, trans), None, workflow, tooltip=False
    )

    assert editor_workflow["steps"][0]["label"] == "sample_reads"
    assert editor_workflow["upgrade_messages"] == {
        0: {
            "workflow_input_name": (
                "Renamed workflow input 'sample|reads' to 'sample_reads' because "
                "'|' is reserved for nested tool inputs."
            )
        }
    }


def test_editor_serialization_upgrades_legacy_subworkflow_interface():
    workflow = yaml_to_model(
        {
            "steps": [
                {"type": "data_input", "label": "source"},
                {
                    "type": "subworkflow",
                    "when_expression": '$(inputs["sample|reads"] !== null)',
                    "subworkflow": {"steps": [{"type": "data_input", "label": "sample|reads"}]},
                    "inputs": {
                        "sample|reads": {
                            "connections": [
                                {
                                    "@output_step": 0,
                                    "output_name": "output",
                                    "@input_subworkflow_step": 0,
                                }
                            ]
                        }
                    },
                },
            ]
        }
    )
    workflow.name = "outer workflow"
    workflow.steps[1].subworkflow.id = 1
    trans = MockTrans()
    manager = WorkflowContentsManager(trans.app, trans.app.trs_proxy)

    editor_workflow = manager._workflow_to_dict_editor(
        cast(ProvidesHistoryContext, trans), None, workflow, tooltip=False
    )
    subworkflow_step = editor_workflow["steps"][1]

    assert subworkflow_step["inputs"][0]["name"] == "sample_reads"
    assert "sample_reads" in subworkflow_step["input_connections"]
    assert subworkflow_step["when"] == '$(inputs["sample_reads"] !== null)'
    assert "subworkflow_input_names" in editor_workflow["upgrade_messages"][1]


def test_saving_legacy_subworkflow_reference_creates_upgraded_copy():
    subworkflow = yaml_to_model({"steps": [{"type": "data_input", "label": "sample|reads"}]})
    subworkflow.name = "legacy subworkflow"
    trans = MockTrans()
    trans.save_workflow(subworkflow)
    manager = WorkflowContentsManager(trans.app, trans.app.trs_proxy)
    step_dict = {
        "type": "subworkflow",
        "content_id": trans.security.encode_id(subworkflow.id),
        "input_connections": {},
        "when": '$(inputs["sample|reads"] !== null)',
    }

    upgraded_subworkflow = manager._WorkflowContentsManager__load_subworkflow_from_step_dict(  # type: ignore[attr-defined]
        cast(ProvidesHistoryContext, trans),
        step_dict,
        subworkflow_id_map=None,
        workflow_state_resolution_options=WorkflowUpdateOptions(),
    )

    assert upgraded_subworkflow is not subworkflow
    assert [step.label for step in upgraded_subworkflow.input_steps] == ["sample_reads"]
    assert upgraded_subworkflow.stored_workflow.hidden
    assert step_dict["when"] == '$(inputs["sample_reads"] !== null)'
