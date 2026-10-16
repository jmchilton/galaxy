from galaxy_test.base.workflow_fixtures import (
    WORKFLOW_OPTIONAL_TRUE_INPUT_DATA,
    WORKFLOW_RUNTIME_PARAMETER_SIMPLE,
    WORKFLOW_SIMPLE_CAT_TWICE,
)
from .framework import (
    managed_history,
    retry_assertion_during_transitions,
    RunsWorkflows,
    selenium_test,
    SeleniumTestCase,
    UsesHistoryItemAssertions,
)
from .upload_activity_helpers import UsesUploadActivity

WORKFLOW_BOOLEAN_PARAMETER_DEFAULT_TRUE = """
class: GalaxyWorkflow
inputs:
  bool_param:
    type: boolean
    default: true
steps:
  echo_bool:
    tool_id: gx_boolean
    in:
      parameter: bool_param
"""


class TestWorkflowRun(SeleniumTestCase, UsesHistoryItemAssertions, RunsWorkflows, UsesUploadActivity):
    ensure_registered = True

    @selenium_test
    @managed_history
    def test_workflow_rerun(self):
        # Run a workflow first
        self.upload_context("local-file").stage_local_file(self.get_filename("1.fasta")).start()
        self.wait_for_history()
        self.workflow_run_open_workflow(WORKFLOW_SIMPLE_CAT_TWICE)
        self.screenshot("workflow_run_before_rerun_ready")
        self.workflow_run_submit()
        self.sleep_for(self.wait_types.UX_TRANSITION)
        self.workflow_run_wait_for_ok(hid=2, expand=True)
        self.assert_item_summary_includes(2, "2 sequences")

        # Keep track of the original history name
        original_history_name = self.history_panel_name()

        # Create a new history, different from the original
        self.history_panel_create_new()
        self.home()
        self._assert_history_name_is("Unnamed history")
        assert self.history_panel_name() != original_history_name

        self.screenshot("workflow_run_before_rerun_complete")

        # Route to rerun
        self.invocation_open_latest()
        self.components.invocations.workflow_rerun_button.wait_for_and_click()

        # Will trigger confirmation modal
        self.components.confirm_dialog.ok_button.wait_for_and_click()
        self.sleep_for(self.wait_types.UX_TRANSITION)

        # Arriving on the rerun page, the history should have switched back to the original history
        self._assert_history_name_is(original_history_name)

        self.screenshot("workflow_rerun_ready")

        # Check input has the original dataset name
        form_element = self.components.workflow_run.form_element._(index=0)
        input_element_value = form_element.select_value.wait_for_visible()
        assert (
            "1: 1.fasta" in input_element_value.text
        ), f"Expected input to be 1.fasta but got {input_element_value.text}"

        # Change input value to latest dataset (as it would be if it wasn't a rerun)
        self.select_set_value(form_element.select, "2:")

        # Find that the changed input badge exists
        form_element.changed_value_badge.wait_for_visible()
        self.screenshot("workflow_rerun_changed_input")

    @selenium_test
    @managed_history
    def test_workflow_rerun_preserves_false_boolean_parameter(self):
        """Regression test for boolean workflow parameters reverting to default on rerun.

        Setting a boolean ``parameter_input`` to ``false`` (overriding a
        ``default: true``), running the workflow, and re-running the invocation
        previously caused the form to silently fall back to the default value
        because of a falsy-value check in WorkflowRunFormSimple.vue. The form
        should instead show the value the user actually used.
        """
        invocations = self.components.invocations

        self.workflow_run_open_workflow(WORKFLOW_BOOLEAN_PARAMETER_DEFAULT_TRUE)

        # Override the boolean default of true to false before submitting.
        # The boolean is the workflow's only input, hence step_index 0.
        self._toggle_workflow_run_boolean(parameter="0", target=False)
        self.screenshot("workflow_run_boolean_false_before_submit")

        self.workflow_run_submit()
        self.sleep_for(self.wait_types.UX_TRANSITION)
        self.workflow_run_wait_for_ok(hid=1)

        # Submitting lands us on the new invocation page; the rerun button is
        # right there on the invocation state details. We're still in the
        # invocation's history, so no "switch history" confirmation appears.
        invocations.state_details.wait_for_visible()
        invocations.workflow_rerun_button.wait_for_and_click()
        self.sleep_for(self.wait_types.UX_TRANSITION)

        # The boolean should be preserved as false on the rerun form rather than
        # silently reset to the workflow's default of true.
        checkbox = self.components.tool_form.parameter_checkbox_input(parameter="0").wait_for_present()
        assert (
            not checkbox.is_selected()
        ), "Boolean parameter input was reset to its default 'true' instead of preserving the previous run's 'false' value"

        # Without changes, the boolean should not be flagged as a changed input.
        form_element = self.components.workflow_run.form_element._(index=0)
        form_element.changed_value_badge.assert_absent()
        self.screenshot("workflow_rerun_boolean_preserved_false")

        # Toggling the value back to true should flag it as changed.
        self._toggle_workflow_run_boolean(parameter="0", target=True)
        form_element.changed_value_badge.wait_for_visible()
        self.screenshot("workflow_rerun_boolean_changed_input")

        # Submit the rerun and verify the new invocation actually recorded the
        # value shown in the form (true) on its Inputs tab.
        self.workflow_run_submit()
        self.sleep_for(self.wait_types.UX_TRANSITION)
        self.workflow_run_wait_for_ok(hid=2)
        invocations.state_details.wait_for_visible()
        invocations.invocation_tab(label="Inputs").wait_for_and_click()
        self._assert_input_table_has_parameter("bool_param", "true")
        self.screenshot("workflow_rerun_boolean_inputs_tab")

    @selenium_test
    @managed_history
    def test_workflow_rerun_with_unset_optional_data_input(self):
        """Regression test for workflow rerun crashing when an optional data_input was left empty.

        When a workflow has an optional ``data_input`` step that the user did
        not provide on the original run, ``WorkflowInvocationRequestModel.inputs``
        returns ``null`` for that step. WorkflowRunFormSimple.vue used to wrap
        the value as ``{values: [null]}`` regardless, which crashed the
        ``FormData`` mounted hook on ``"src" in null``. Because the mounted
        hook never completed, the bad wrapper survived in formData and was
        sent to the server, which rejected it with a ``DataOrCollectionRequest``
        union ValidationError ("Extra inputs are not permitted in 'values'").
        Reported on a "1 or 2 haplotypes" workflow where the second haplotype
        was left empty.
        """
        invocations = self.components.invocations

        # Upload one HDA so the history isn't empty (the workflow form needs a
        # current history); the optional input is intentionally left unselected.
        self.upload_context("local-file").stage_local_file(self.get_filename("1.fasta")).start()
        self.wait_for_history()
        self.workflow_run_open_workflow(WORKFLOW_OPTIONAL_TRUE_INPUT_DATA)
        self.workflow_run_submit()
        self.sleep_for(self.wait_types.UX_TRANSITION)
        self.workflow_run_wait_for_ok(hid=2, expand=True)

        # Submitting lands us on the new invocation page; click rerun directly.
        invocations.state_details.wait_for_visible()
        invocations.workflow_rerun_button.wait_for_and_click()
        self.sleep_for(self.wait_types.UX_TRANSITION)

        # Submit the rerun without touching anything. Pre-fix this raises a
        # "Workflow submission failed: ... 'values' not permitted ..." toast
        # because formData carries the poisoned `{values: [null]}` wrapper.
        self.workflow_run_submit()
        self.sleep_for(self.wait_types.UX_TRANSITION)
        self.workflow_run_wait_for_ok(hid=3, expand=True)
        self.screenshot("workflow_rerun_unset_optional_data_input_submitted")

    @selenium_test
    @managed_history
    def test_workflow_rerun_prefills_expanded_form(self):
        """Rerunning an invocation that set tool step parameters opens the expanded form prefilled from that run."""
        workflow_run = self.components.workflow_run
        tool_form = self.components.tool_form
        history_id = self.current_history_id()

        plain = self.workflow_populator.run_workflow(
            WORKFLOW_RUNTIME_PARAMETER_SIMPLE,
            test_data={"step_parameters": {"1": {"num_lines": 3}}, "input1": {"value": "1.bed", "type": "File"}},
            history_id=history_id,
        )
        self.get(f"workflows/rerun?invocation_id={plain.invocation_id}")
        # Seeding fills num_lines, so only the recorded step parameters keep this out of the simplified form.
        workflow_run.expanded_form.wait_for_visible()
        assert not workflow_run.job_reuse_checkbox.wait_for_present().is_selected()
        self.workflow_run_expand_step("random")
        self._assert_tool_parameter_preview("num_lines", "3")
        self.screenshot("workflow_rerun_expanded_form_seeded_step")

        workflow = WORKFLOW_RUNTIME_PARAMETER_SIMPLE.replace("seed: asdf", "seed: ${seedme}")
        with_params = self.workflow_populator.run_workflow(
            workflow,
            test_data={
                "step_parameters": {"1": {"num_lines": 2}},
                "replacement_parameters": {"seedme": "moo"},
                "input1": {"value": "1.bed", "type": "File"},
            },
            history_id=history_id,
            use_cached_job=True,
        )
        self.get(f"workflows/rerun?invocation_id={with_params.invocation_id}")
        workflow_run.expanded_form.wait_for_visible()
        seedme = tool_form.parameter_input(parameter="seedme").wait_for_visible()
        assert seedme.get_attribute("value") == "moo", seedme.get_attribute("value")
        assert workflow_run.job_reuse_checkbox.wait_for_present().is_selected()
        self.screenshot("workflow_rerun_expanded_form_seeded_workflow_parameters")
        self.workflow_run_expand_step("random")
        self._assert_tool_parameter_preview("num_lines", "2")
        self.screenshot("workflow_rerun_expanded_form_seeded_workflow_parameters_step")

    @retry_assertion_during_transitions
    def _assert_tool_parameter_preview(self, parameter: str, expected: str):
        preview = self.components.tool_form.parameter_preview(parameter=parameter).wait_for_visible()
        self.scroll_into_view(preview)
        assert preview.text.strip() == expected, f"Expected {parameter} to show {expected!r}, got {preview.text!r}"

    @retry_assertion_during_transitions
    def _assert_input_table_has_parameter(self, label: str, value: str):
        table = self.wait_for_selector('[data-description="input table"]')
        text = table.text
        assert label in text, f"Expected input label '{label}' in inputs table, got: {text!r}"
        assert value in text, f"Expected input value '{value}' in inputs table, got: {text!r}"

    def _toggle_workflow_run_boolean(self, parameter: str, target: bool):
        checkbox = self.components.tool_form.parameter_checkbox_input(parameter=parameter).wait_for_present()
        if checkbox.is_selected() != target:
            self.execute_script("arguments[0].click();", checkbox)

    @retry_assertion_during_transitions
    def _assert_history_name_is(self, expected_name=None):
        name = self.history_panel_name()
        assert name == expected_name, f"History name should be {expected_name} but is {name}"
