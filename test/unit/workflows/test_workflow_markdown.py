from galaxy import model
from galaxy.managers.markdown_util import resolve_invocation_markdown

from .workflow_support import MockTrans, yaml_to_model
from .test_workflow_progress import TEST_WORKFLOW_YAML


def test_workflow_section_expansion():
    workflow_markdown = """
## Workflow
::: workflow_display
:::
"""
    galaxy_markdown = resolved_markdown(workflow_markdown)
    assert "## Workflow\n" in galaxy_markdown
    assert "::: workflow_display workflow_id=342\n:::\n" in galaxy_markdown


def test_inputs_section_expansion():
    workflow_markdown = """
## Workflow Inputs
::: invocation_inputs
:::
"""
    galaxy_markdown = resolved_markdown(workflow_markdown)
    assert "## Workflow Inputs" in galaxy_markdown
    assert "::: history_dataset_display history_dataset_id=567" in galaxy_markdown
    assert len(galaxy_markdown.split(":::")) == 3


def test_outputs_section_expansion():
    workflow_markdown = """
## Workflow Outputs
::: invocation_outputs
:::
"""
    galaxy_markdown = resolved_markdown(workflow_markdown)
    assert "## Workflow Outputs" in galaxy_markdown
    assert "::: history_dataset_display history_dataset_id=563" in galaxy_markdown


def test_fenced_section_expansion():
    workflow_markdown = """
```
## Workflow Outputs
::: invocation_outputs
:::
```
"""
    galaxy_markdown = resolved_markdown(workflow_markdown)
    assert "## Workflow Outputs" in galaxy_markdown
    assert "::: history_dataset_display history_dataset_id=563" not in galaxy_markdown
    assert "::: invocation_outputs\n:::" in galaxy_markdown


def test_input_reference_mapping():
    workflow_markdown = """
And outputs...

::: history_dataset_peek input=input1
:::
"""
    galaxy_markdown = resolved_markdown(workflow_markdown)
    assert "::: history_dataset_peek history_dataset_id=567" in galaxy_markdown


def test_output_reference_mapping():
    workflow_markdown = """
And outputs...

::: history_dataset_as_image output=output_label
:::
"""
    galaxy_markdown = resolved_markdown(workflow_markdown)
    assert "::: history_dataset_as_image history_dataset_id=563" in galaxy_markdown


def resolved_markdown(workflow_markdown):
    # Convert workflow markdown to internal Galaxy markdown with object id references
    # and with sections expanded.
    trans = MockTrans()
    galaxy_markdown = resolve_invocation_markdown(trans, example_invocation(trans), workflow_markdown)
    return galaxy_markdown


def example_invocation(trans):
    invocation = model.WorkflowInvocation()
    workflow = yaml_to_model(TEST_WORKFLOW_YAML)
    workflow.id = 342
    invocation.workflow = workflow
    hda = model.HistoryDatasetAssociation(create_dataset=True, sa_session=trans.sa_session)
    hda.id = 567
    invocation.add_input(hda, step=workflow.steps[0])
    out_hda = model.HistoryDatasetAssociation(create_dataset=True, sa_session=trans.sa_session)
    out_hda.id = 563
    wf_output = model.WorkflowOutput(workflow.steps[2], label="output_label")
    invocation.add_output(wf_output, workflow.steps[2], out_hda)
    return invocation
