from galaxy import model
from galaxy.managers.workflows import (
    _workflow_input_name_upgrades,
    WorkflowContentsManager,
)
from .workflow_support import MockTrans


def _workflow_with_steps(*steps: tuple[str, str]) -> model.Workflow:
    workflow = model.Workflow()
    workflow.name = "workflow input name test"
    workflow.steps = []
    for order_index, (step_type, label) in enumerate(steps):
        step = model.WorkflowStep()
        step.order_index = order_index
        step.type = step_type
        step.label = label
        step.tool_inputs = {}
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


def test_editor_serialization_upgrades_legacy_workflow_input_name():
    workflow = _workflow_with_steps(("data_input", "sample|reads"))
    trans = MockTrans()
    manager = WorkflowContentsManager(trans.app, trans.app.trs_proxy)

    editor_workflow = manager._workflow_to_dict_editor(trans, None, workflow, tooltip=False)

    assert editor_workflow["steps"][0]["label"] == "sample_reads"
    assert editor_workflow["upgrade_messages"] == {
        0: {
            "workflow_input_name": (
                "Renamed workflow input 'sample|reads' to 'sample_reads' because "
                "'|' is reserved for nested tool inputs."
            )
        }
    }
