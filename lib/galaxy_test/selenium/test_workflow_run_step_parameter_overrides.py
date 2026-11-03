"""Choosing tool step parameters (``step_parameter_overrides``) in the simple workflow run form."""

import json
from urllib.parse import quote

from galaxy_test.base.populators import wait_on
from galaxy_test.base.workflow_fixtures import (
    WORKFLOW_STEP_PARAMETER_OVERRIDES,
    WORKFLOW_STEP_PARAMETER_OVERRIDES_NESTED,
)
from .framework import (
    managed_history,
    retry_assertion_during_transitions,
    RunsWorkflows,
    selenium_test,
    SeleniumTestCase,
    UsesHistoryItemAssertions,
)

# The echo step's index in WORKFLOW_STEP_PARAMETER_OVERRIDES (after the table and threshold_param inputs).
ECHO = "2"


class TestWorkflowRunStepParameterOverrides(SeleniumTestCase, UsesHistoryItemAssertions, RunsWorkflows):
    ensure_registered = True

    def _table(self, history_id: str) -> dict:
        return self.dataset_populator.new_dataset(history_id, content="1\t2\t3\n", file_type="tabular", wait=True)

    def _run_api(self, history_id: str, workflow_id: str, hda_id: str, **extra) -> str:
        request = {
            "history_id": history_id,
            "inputs": {"0": {"src": "hda", "id": hda_id}},
            "inputs_by": "step_index",
            **extra,
        }
        response = self.workflow_populator.invoke_workflow_raw(workflow_id, request, assert_ok=True)
        invocation_id = response.json()["id"]
        self.workflow_populator.wait_for_invocation_and_jobs(history_id, workflow_id, invocation_id)
        return invocation_id

    def _echo(self, history_id: str, invocation_id: str) -> dict[str, str]:
        self.workflow_populator.wait_for_invocation_and_jobs(history_id, None, invocation_id)
        invocation = self.workflow_populator.get_invocation(invocation_id)
        content = self.dataset_populator.get_history_dataset_content(
            history_id, dataset_id=invocation["outputs"]["echo"]["id"]
        )
        return dict(line.split("=", 1) for line in content.splitlines() if line)

    def _submit(self, history_id: str, known: frozenset[str] = frozenset()) -> str:
        """Submit the run form; return the single new top-level invocation (subworkflow invocations are left out)."""
        self.workflow_run_submit()

        def new_invocation_ids():
            invocations = self.workflow_populator.history_invocations(history_id, include_nested_invocations=False)
            return [i["id"] for i in invocations if i["id"] not in known] or None

        [new] = wait_on(new_invocation_ids, "new workflow invocation")
        return new

    def _assert_request_overrides(self, invocation_id: str, expected: dict) -> dict:
        request = self.workflow_populator.invocation_to_request(invocation_id)
        assert request["step_parameter_overrides"] == expected, request
        return request

    def _open_link(self, workflow_id: str, step_parameter_overrides: str):
        """Open the run form from a link carrying the (JSON) step_parameter_overrides route argument."""
        self.get(f"workflows/run?id={workflow_id}&step_parameter_overrides={quote(step_parameter_overrides)}")

    def _open_rerun(self, invocation_id: str):
        self.get(f"workflows/rerun?invocation_id={invocation_id}")

    def _assert_rerun_expanded(self, reason: str):
        """The rerun opened the expanded form, saying why the simple form can't show the original run."""
        workflow_run = self.components.workflow_run
        workflow_run.expanded_form.wait_for_visible()
        reason_text = workflow_run.simple_form_disabled_reason.wait_for_visible().text
        assert reason in reason_text, reason_text

    def _choose(self, *keys: str):
        step_parameters = self.components.workflow_run.step_parameters
        step_parameters.choose.wait_for_and_click()
        step_parameters.picker.wait_for_visible()
        for key in keys:
            step_parameters.picker_parameter(key=key).wait_for_and_click()

    def _apply(self):
        self.components.workflow_run.step_parameters.picker_apply.wait_for_and_click()
        self.components.workflow_run.step_parameters.picker.wait_for_absent_or_hidden()

    def _open_workflow_view(self, from_picker: bool = False):
        step_parameters = self.components.workflow_run.step_parameters
        if from_picker:
            step_parameters.picker_workflow_view.wait_for_and_click()
        else:
            step_parameters.open_workflow_view.wait_for_and_click()
        step_parameters.workflow_node(order_index=0).wait_for_visible()

    def _choose_in_workflow_view(self, order_index: int, *keys: str, from_step_select: bool = False):
        step_parameters = self.components.workflow_run.step_parameters
        if from_step_select:
            # The panel's step select is the keyboard alternative to clicking a node.
            step_parameters.workflow_step_select.wait_for_visible()
            step_parameters.workflow_step_select.select_by_value(str(order_index))
        else:
            step_parameters.workflow_node_title(order_index=order_index).wait_for_and_click()
        for key in keys:
            step_parameters.workflow_panel_parameter(key=key).wait_for_and_click()

    @retry_assertion_during_transitions
    def _assert_workflow_node_text(self, order_index: int, expected: str):
        text = (
            self.components.workflow_run.step_parameters.workflow_node(order_index=order_index).wait_for_visible().text
        )
        assert expected in text, text

    def _set_card_value(self, key: str, value: str):
        self.components.workflow_run.step_parameters.card_input(key=key).wait_for_and_clear_and_send_keys(value)

    @retry_assertion_during_transitions
    def _assert_card_value(self, key: str, expected: str):
        value = self.components.workflow_run.step_parameters.card_input(key=key).wait_for_value()
        assert value == expected, f"{key}: expected {expected!r}, got {value!r}"

    def _assert_picker_details(self):
        step_parameters = self.components.workflow_run.step_parameters
        threshold = f"{ECHO}/threshold"
        row_text = step_parameters.picker_row(key=threshold).wait_for_visible().text
        assert "workflow sets to 0.5" in row_text, row_text

        step_parameters.picker_help(key=threshold).wait_for_and_click()
        popover = step_parameters.help_popover(key=threshold).wait_for_visible()
        assert popover.text == "Scores below this are dropped.", popover.text
        self.send_escape()
        step_parameters.help_popover(key=threshold).wait_for_absent_or_hidden()
        step_parameters.picker.wait_for_visible()

        # The conditional's row shows its test parameter, locked.
        cond = f"{ECHO}/cond"
        row_text = step_parameters.picker_row(key=cond).wait_for_visible().text
        assert "workflow sets to Minimum" in row_text, row_text
        self.hover(step_parameters.picker_lock(key=cond).wait_for_visible())
        tooltip = step_parameters.lock_tooltip(key=cond).wait_for_visible()
        assert "Set it in the expanded form" in tooltip.text, tooltip.text
        self.screenshot("step_parameter_overrides_picker_locked_conditional")
        self.hover_away()

    @selenium_test
    @managed_history
    def test_choose_step_parameters_and_run(self):
        history_id = self.current_history_id()
        self._table(history_id)
        self.workflow_run_open_workflow(WORKFLOW_STEP_PARAMETER_OVERRIDES)
        step_parameters = self.components.workflow_run.step_parameters
        step_parameters._.wait_for_visible()
        self.components.workflow_run.expanded_form.assert_absent()
        self.screenshot("step_parameter_overrides_empty")

        self._choose(f"{ECHO}/threshold", f"{ECHO}/queries/1/column_name", f"{ECHO}/cond/min", f"{ECHO}/mode")
        self._assert_picker_details()
        step_parameters.picker_filter.wait_for_visible().send_keys("query")
        step_parameters.picker_row(key=f"{ECHO}/threshold").wait_for_absent()
        step_parameters.picker_row(key=f"{ECHO}/queries/1/column_name").wait_for_visible()
        self.screenshot("step_parameter_overrides_picker_filtered")
        self._apply()

        self._assert_card_value(f"{ECHO}/threshold", "0.5")
        self._set_card_value(f"{ECHO}/threshold", "0.9")
        self._set_card_value(f"{ECHO}/queries/1/column_name", "c9")
        self._set_card_value(f"{ECHO}/cond/min", "5")
        self.screenshot("step_parameter_overrides_cards")

        # Removing a card drops the override, and so does unchecking it in the picker. The cards that stay keep
        # what was typed in them while others come and go.
        step_parameters.card_remove(key=f"{ECHO}/queries/1/column_name").wait_for_and_click()
        step_parameters.card(key=f"{ECHO}/queries/1/column_name").wait_for_absent()
        self._choose(f"{ECHO}/mode", f"{ECHO}/advanced/label")
        self._apply()
        step_parameters.card(key=f"{ECHO}/mode").wait_for_absent()
        self._assert_card_value(f"{ECHO}/advanced/label", "run")
        self._assert_card_value(f"{ECHO}/threshold", "0.9")
        self._assert_card_value(f"{ECHO}/cond/min", "5")

        invocation_id = self._submit(history_id)
        echo = self._echo(history_id, invocation_id)
        assert echo["threshold"] == "0.9", echo
        assert echo["cond.min"] == "5", echo
        assert echo["queries_1.column_name"] == "c2", echo
        request = self._assert_request_overrides(
            invocation_id, {ECHO: {"threshold": 0.9, "advanced": {"label": "run"}, "cond": {"min": 5}}}
        )
        assert request["parameters"] is None, request

    @selenium_test
    @managed_history
    def test_choose_in_workflow_view_and_run(self):
        history_id = self.current_history_id()
        self._table(history_id)
        self.workflow_run_open_workflow(WORKFLOW_STEP_PARAMETER_OVERRIDES)
        step_parameters = self.components.workflow_run.step_parameters
        self._open_workflow_view()
        self._assert_workflow_node_text(int(ECHO), "to choose from")
        self._choose_in_workflow_view(int(ECHO), f"{ECHO}/threshold", f"{ECHO}/cond/min")
        self._assert_workflow_node_text(int(ECHO), "2 of")
        # The panel is titled with the step number the node and the list show.
        assert "Step 3: echo" in step_parameters.workflow_panel.wait_for_visible().text
        self.screenshot("step_parameter_overrides_workflow_view")
        self._apply()
        step_parameters.card(key=f"{ECHO}/threshold").wait_for_visible()

        # Unchecking in the workflow view removes the card.
        self._open_workflow_view()
        self._choose_in_workflow_view(int(ECHO), f"{ECHO}/threshold")
        self._assert_workflow_node_text(int(ECHO), "1 of")
        self._apply()
        step_parameters.card(key=f"{ECHO}/threshold").wait_for_absent()
        self._set_card_value(f"{ECHO}/cond/min", "5")

        invocation_id = self._submit(history_id)
        echo = self._echo(history_id, invocation_id)
        assert echo["cond.min"] == "5", echo
        assert echo["threshold"] == "0.5", echo
        self._assert_request_overrides(invocation_id, {ECHO: {"cond": {"min": 5}}})

    @selenium_test
    @managed_history
    def test_list_and_workflow_view_share_picked_parameters(self):
        history_id = self.current_history_id()
        self._table(history_id)
        self.workflow_run_open_workflow(WORKFLOW_STEP_PARAMETER_OVERRIDES_NESTED)
        step_parameters = self.components.workflow_run.step_parameters
        self._choose("1/1/threshold")

        # The subworkflow node counts, and its panel lists, the parameters of the steps inside it.
        self._open_workflow_view(from_picker=True)
        self._assert_workflow_node_text(1, "1 of")
        self._choose_in_workflow_view(1, "1/1/cond/min", from_step_select=True)
        assert step_parameters.workflow_panel_parameter(key="1/1/threshold").wait_for_present().is_selected()
        self._assert_workflow_node_text(1, "2 of")
        # The inner step's number restarts inside the subworkflow, so its label leads with the subworkflow.
        assert "nested › Step 2: echo" in step_parameters.workflow_panel.wait_for_visible().text
        self.screenshot("step_parameter_overrides_workflow_view_subworkflow")

        step_parameters.picker_list_view.wait_for_and_click()
        assert step_parameters.picker_parameter(key="1/1/cond/min").wait_for_visible().is_selected()
        step_parameters.picker_parameter(key="1/1/threshold").wait_for_and_click()
        self._apply()
        step_parameters.card(key="1/1/threshold").wait_for_absent()
        self._set_card_value("1/1/cond/min", "3")

        invocation_id = self._submit(history_id)
        assert self._echo(history_id, invocation_id)["cond.min"] == "3"
        self._assert_request_overrides(invocation_id, {"1": {"1": {"cond": {"min": 3}}}})

    @selenium_test
    @managed_history
    def test_choose_subworkflow_step_parameter(self):
        history_id = self.current_history_id()
        self._table(history_id)
        self.workflow_run_open_workflow(WORKFLOW_STEP_PARAMETER_OVERRIDES_NESTED)
        step_parameters = self.components.workflow_run.step_parameters
        # Closing the picker without applying discards what was picked.
        self._choose("1/1/threshold")
        step_parameters.picker_cancel.wait_for_and_click()
        step_parameters.picker.wait_for_absent_or_hidden()
        step_parameters.card(key="1/1/threshold").assert_absent()
        self._choose()
        assert not step_parameters.picker_parameter(key="1/1/threshold").wait_for_present().is_selected()

        step_parameters.picker_parameter(key="1/1/threshold").wait_for_and_click()
        self.screenshot("step_parameter_overrides_picker_subworkflow")
        self._apply()
        self._set_card_value("1/1/threshold", "0.9")
        invocation_id = self._submit(history_id)
        assert self._echo(history_id, invocation_id)["threshold"] == "0.9"
        self._assert_request_overrides(invocation_id, {"1": {"1": {"threshold": 0.9}}})

    @selenium_test
    @managed_history
    def test_server_errors_land_on_their_cards(self):
        history_id = self.current_history_id()
        self._table(history_id)
        self.workflow_run_open_workflow(WORKFLOW_STEP_PARAMETER_OVERRIDES_NESTED)
        step_parameters = self.components.workflow_run.step_parameters
        self._choose("1/1/advanced/label", "1/1/threshold")
        self._apply()
        # Only the server checks this validator, and it reports the error by the subworkflow's and its step's indexes.
        self._set_card_value("1/1/advanced/label", "Tuned")
        self.workflow_run_submit()
        error = step_parameters.card_error(key="1/1/advanced/label").wait_for_visible()
        assert "Run labels are lowercase" in error.text, error.text
        step_parameters.card_error(key="1/1/threshold").assert_absent()
        alert = self.components.workflow_run.run_error.wait_for_visible()
        assert "Fix the step parameters marked below" in alert.text, alert.text
        self.screenshot("step_parameter_overrides_card_error")

        # Changing the value clears its error.
        self._set_card_value("1/1/advanced/label", "tuned")
        step_parameters.card_error(key="1/1/advanced/label").wait_for_absent()
        invocation_id = self._submit(history_id)
        assert self._echo(history_id, invocation_id)["advanced.label"] == "tuned"
        self._assert_request_overrides(invocation_id, {"1": {"1": {"advanced": {"label": "tuned"}, "threshold": 0.5}}})

    @selenium_test
    @managed_history
    def test_rerun_reshows_step_parameter_overrides(self):
        history_id = self.current_history_id()
        hda = self._table(history_id)
        workflow_id = self.workflow_populator.upload_yaml_workflow(WORKFLOW_STEP_PARAMETER_OVERRIDES_NESTED)
        overrides = {"1": {"1": {"threshold": 0.75, "cond": {"min": 3}}}}
        invocation_id = self._run_api(history_id, workflow_id, hda["id"], step_parameter_overrides=overrides)
        self._open_rerun(invocation_id)
        self._assert_card_value("1/1/threshold", "0.75")
        self._assert_card_value("1/1/cond/min", "3")
        card = self.components.workflow_run.step_parameters.card(key="1/1/threshold").wait_for_visible()
        assert "original run: 0.75" in card.text, card.text
        self.components.workflow_run.expanded_form.assert_absent()
        self.screenshot("step_parameter_overrides_rerun_prefilled")

        rerun_id = self._submit(history_id, frozenset({invocation_id}))
        self._assert_request_overrides(rerun_id, overrides)

    @selenium_test
    @managed_history
    def test_rerun_with_legacy_step_parameters_stays_expanded(self):
        history_id = self.current_history_id()
        hda = self._table(history_id)
        workflow_id = self.workflow_populator.upload_yaml_workflow(WORKFLOW_STEP_PARAMETER_OVERRIDES)
        invocation_id = self._run_api(
            history_id, workflow_id, hda["id"], parameters={ECHO: {"threshold": 0.75}}, parameters_normalized=True
        )
        self._open_rerun(invocation_id)
        self._assert_rerun_expanded("didn't record which tool step parameters were chosen")

    @selenium_test
    @managed_history
    def test_rerun_with_switched_conditional_case_stays_expanded(self):
        history_id = self.current_history_id()
        hda = self._table(history_id)
        workflow_id = self.workflow_populator.upload_yaml_workflow(WORKFLOW_STEP_PARAMETER_OVERRIDES)
        overrides = {ECHO: {"cond": {"filter_type": "regex", "pattern": "^chr"}}}
        invocation_id = self._run_api(history_id, workflow_id, hda["id"], step_parameter_overrides=overrides)
        self._open_rerun(invocation_id)
        # The simple form can't show a switched conditional case, so the expanded form shows the original run.
        self._assert_rerun_expanded("can't show, such as a conditional's selected case")
        self.workflow_run_expand_step("echo")
        preview = self.components.tool_form.parameter_preview(parameter="cond|pattern").wait_for_visible()
        assert preview.text.strip() == "^chr", preview.text
        self.screenshot("step_parameter_overrides_rerun_switched_case_expanded")

        rerun_id = self._submit(history_id, frozenset({invocation_id}))
        echo = self._echo(history_id, rerun_id)
        assert echo["cond.filter_type"] == "regex", echo
        assert echo["cond.pattern"] == "^chr", echo

    @selenium_test
    @managed_history
    def test_rerun_with_this_changed(self):
        history_id = self.current_history_id()
        hda = self._table(history_id)
        workflow_id = self.workflow_populator.upload_yaml_workflow(WORKFLOW_STEP_PARAMETER_OVERRIDES)
        invocation_id = self._run_api(history_id, workflow_id, hda["id"])
        self.get(f"workflows/invocations/{invocation_id}")
        invocations = self.components.invocations
        invocations.invocation_tab(label="Steps").wait_for_and_click()
        invocations.step_details(order_index=ECHO).wait_for_and_click()
        link = invocations.rerun_with_this_changed(path="cond/min").wait_for_visible()
        # The step's job details keep loading after its parameters show, moving the link, so let them settle first.
        self.sleep_for(self.wait_types.UX_RENDER)
        self.scroll_into_view(link)
        self.hover(link)
        self.components._.tooltip_inner.wait_for_visible()
        self.screenshot("step_parameter_overrides_rerun_with_this_changed")
        self.clear_tooltips()
        invocations.rerun_with_this_changed(path="queries/1/column_name").wait_for_visible()
        # The conditional's test parameter and the data-dependent column are not offered.
        invocations.rerun_with_this_changed(path="cond/filter_type").assert_absent()
        invocations.rerun_with_this_changed(path="column").assert_absent()
        invocations.rerun_with_this_changed(path="cond/min").wait_for_and_click()

        self._assert_card_value(f"{ECHO}/cond/min", "1")
        self.components.workflow_run.expanded_form.assert_absent()
        self._set_card_value(f"{ECHO}/cond/min", "4")
        rerun_id = self._submit(history_id, frozenset({invocation_id}))
        assert self._echo(history_id, rerun_id)["cond.min"] == "4"

    @selenium_test
    @managed_history
    def test_link_with_preset_and_unusable_parameters(self):
        history_id = self.current_history_id()
        self._table(history_id)
        workflow_id = self.workflow_populator.upload_yaml_workflow(WORKFLOW_STEP_PARAMETER_OVERRIDES)
        step_parameters = self.components.workflow_run.step_parameters
        self._open_link(workflow_id, "{")
        assert "not valid JSON" in step_parameters.link_error.wait_for_visible().text

        overrides = {ECHO: {"cond": {"min": 7, "pattern": None}, "column": None, "threshold": None}}
        self._open_link(workflow_id, json.dumps(overrides))
        self._assert_card_value(f"{ECHO}/cond/min", "7")
        self._assert_card_value(f"{ECHO}/threshold", "0.5")
        threshold_card = step_parameters.card(key=f"{ECHO}/threshold").wait_for_visible()
        assert "saved: 0.5" in threshold_card.text, threshold_card.text
        # Each dropped parameter says why: one isn't in the saved conditional case, one's options come from data.
        pattern = step_parameters.dropped_parameter(key=f"{ECHO}/cond/pattern").wait_for_visible().text
        assert "Step 3: echo › Filter type › pattern" in pattern, pattern
        assert "no such parameter in the workflow's current state" in pattern, pattern
        column = step_parameters.dropped_parameter(key=f"{ECHO}/column").wait_for_visible().text
        assert "Step 3: echo › Column" in column, column
        assert "Options depend on a data input" in column, column
        self.screenshot("step_parameter_overrides_link_preset_and_dropped")

        # A null link value runs with the workflow's value, typed as the tool form types it; dropped ones aren't sent.
        invocation_id = self._submit(history_id)
        assert self._echo(history_id, invocation_id)["cond.min"] == "7"
        self._assert_request_overrides(invocation_id, {ECHO: {"cond": {"min": 7}, "threshold": 0.5}})

    @selenium_test
    @managed_history
    def test_link_in_expanded_form_lists_its_parameters(self):
        self._table(self.current_history_id())
        workflow_id = self.workflow_populator.upload_yaml_workflow(WORKFLOW_STEP_PARAMETER_OVERRIDES)
        workflow_run = self.components.workflow_run
        self._open_link(workflow_id, "{")
        self.workflow_run_ensure_expanded()
        alert = workflow_run.linked_step_parameters.wait_for_visible()
        assert "not valid JSON" in alert.text, alert.text

        # The expanded form can't preset a link's parameters, so it names them for setting in their steps.
        overrides = {ECHO: {"threshold": None, "cond": {"min": 7}}}
        self._open_link(workflow_id, json.dumps(overrides))
        self.workflow_run_ensure_expanded()
        alert = workflow_run.linked_step_parameters.wait_for_visible()
        assert "can't preset" in alert.text, alert.text
        threshold = workflow_run.linked_step_parameter(key=f"{ECHO}/threshold").wait_for_visible()
        assert "Step 3: echo › Threshold" in threshold.text, threshold.text
        cond_min = workflow_run.linked_step_parameter(key=f"{ECHO}/cond/min").wait_for_visible()
        assert "Minimum value" in cond_min.text, cond_min.text
        self.screenshot("step_parameter_overrides_link_expanded_form")
