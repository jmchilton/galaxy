from galaxy import model
from galaxy.managers.workflows import (
    _workflow_input_name_upgrades,
    WorkflowContentsManager,
    WorkflowUpdateOptions,
)
from .workflow_support import (
    MockTrans,
    yaml_to_model,
)


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
    trans.security = trans.app.security
    manager = WorkflowContentsManager(trans.app, trans.app.trs_proxy)

    editor_workflow = manager._workflow_to_dict_editor(trans, None, workflow, tooltip=False)
    subworkflow_step = editor_workflow["steps"][1]

    assert subworkflow_step["inputs"][0]["name"] == "sample_reads"
    assert "sample_reads" in subworkflow_step["input_connections"]
    assert subworkflow_step["when"] == '$(inputs["sample_reads"] !== null)'
    assert "subworkflow_input_names" in editor_workflow["upgrade_messages"][1]


def test_saving_legacy_subworkflow_reference_creates_upgraded_copy():
    subworkflow = yaml_to_model({"steps": [{"type": "data_input", "label": "sample|reads"}]})
    subworkflow.name = "legacy subworkflow"
    trans = MockTrans()
    trans.security = trans.app.security
    trans.get_user = lambda: trans.user
    trans.save_workflow(subworkflow)
    manager = WorkflowContentsManager(trans.app, trans.app.trs_proxy)
    step_dict = {
        "type": "subworkflow",
        "content_id": trans.security.encode_id(subworkflow.id),
        "input_connections": {},
        "when": '$(inputs["sample|reads"] !== null)',
    }

    upgraded_subworkflow = manager._WorkflowContentsManager__load_subworkflow_from_step_dict(
        trans,
        step_dict,
        subworkflow_id_map=None,
        workflow_state_resolution_options=WorkflowUpdateOptions(),
    )

    assert upgraded_subworkflow is not subworkflow
    assert [step.label for step in upgraded_subworkflow.input_steps] == ["sample_reads"]
    assert upgraded_subworkflow.stored_workflow.hidden
    assert step_dict["when"] == '$(inputs["sample_reads"] !== null)'
