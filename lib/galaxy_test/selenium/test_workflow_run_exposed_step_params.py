"""Spike: exposing individual step parameters in the simple workflow run form."""

from galaxy_test.base.workflow_fixtures import WORKFLOW_EXPOSED_STEP_PARAMS
from .framework import (
    managed_history,
    retry_assertion_during_transitions,
    RunsWorkflows,
    selenium_test,
    SeleniumTestCase,
    UsesHistoryItemAssertions,
)

CARDS = '[data-description="workflow run step parameters"]'
PICKER_OK = ".g-modal-confirm-buttons button:last-child"


def _card(key: str) -> str:
    return f'.step-parameter-card[data-exposure-key="{key}"]'


def _as_strings(parameters: dict) -> dict:
    """Form submissions send scalar values as strings."""
    return {step: {k: str(v) for k, v in params.items()} for step, params in parameters.items()}


class TestWorkflowRunExposedStepParams(SeleniumTestCase, UsesHistoryItemAssertions, RunsWorkflows):
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
        invocation = self.workflow_populator.get_invocation(invocation_id)
        content = self.dataset_populator.get_history_dataset_content(
            history_id, dataset_id=invocation["outputs"]["echo"]["id"]
        )
        return dict(line.split("=", 1) for line in content.splitlines() if line)

    def _set_card_value(self, key: str, value: str):
        field = self.wait_for_selector_visible(f"{_card(key)} .ui-input")
        field.clear()
        field.send_keys(value)

    @retry_assertion_during_transitions
    def _assert_card_value(self, key: str, expected: str):
        value = self.wait_for_selector_visible(f"{_card(key)} .ui-input").get_attribute("value")
        assert value == expected, f"{key}: expected {expected!r}, got {value!r}"

    def _new_invocation_id(self, history_id: str, known: set[str]) -> str:
        self.workflow_populator.wait_for_history_workflows(history_id, expected_invocation_count=len(known) + 1)
        [new] = [i["id"] for i in self.workflow_populator.history_invocations(history_id) if i["id"] not in known]
        return new

    def _assert_tree_row_details(self):
        threshold_row = '.step-param-row:has(> label[data-exposure-key="1|threshold"])'
        row_text = self.wait_for_selector_visible(threshold_row).text
        assert "workflow sets to 0.5" in row_text, row_text
        assert "1|threshold" not in row_text, row_text

        self.wait_for_selector_clickable(f'{threshold_row} [data-description="step parameter help"]').click()
        popover = self.wait_for_selector_visible(".popover-body")
        assert popover.text == "Scores below this are dropped.", popover.text
        self.screenshot("exposed_step_params_picker_help")
        self.send_escape()
        self.wait_for_selector_absent_or_hidden(".popover-body")
        self.wait_for_selector_visible('[data-description="step parameter picker"]')

        cond_row = ".step-param-conditional > .step-param-row.step-param-locked"
        assert "workflow sets to Minimum" in self.wait_for_selector_visible(cond_row).text
        self.hover(self.wait_for_selector_visible(f'{cond_row} [data-description="step parameter locked"]'))
        tooltip = self.wait_for_selector_visible('.g-tooltip[data-show="true"]')
        assert "Set it in the expanded form" in tooltip.text, tooltip.text
        self.screenshot("exposed_step_params_picker_locked_conditional")
        self.hover_away()

    @selenium_test
    @managed_history
    def test_add_step_parameters_and_run(self):
        history_id = self.current_history_id()
        self._table(history_id)
        self.workflow_run_open_workflow(WORKFLOW_EXPOSED_STEP_PARAMS)
        self.wait_for_selector_visible(CARDS)
        self.components.workflow_run.expanded_form.assert_absent()
        self.screenshot("exposed_step_params_empty")

        self.wait_for_selector_clickable('[data-description="add step parameter"]').click()
        self.wait_for_selector_visible('[data-exposure-key="1|threshold"] input')
        self.screenshot("exposed_step_params_picker")
        self._assert_tree_row_details()
        for key in ["1|threshold", "1|queries_1|column_name", "1|cond|min"]:
            self.wait_for_selector_clickable(f'label[data-exposure-key="{key}"] input').click()
        self.screenshot("exposed_step_params_picker_selected")
        filter_input = self.wait_for_selector_visible('[data-description="step parameter filter"]')
        filter_input.send_keys("query")
        self.sleep_for(self.wait_types.UX_RENDER)
        self.screenshot("exposed_step_params_picker_filtered")
        self.wait_for_selector_clickable(PICKER_OK).click()

        self._assert_card_value("1|threshold", "0.5")
        self._set_card_value("1|threshold", "0.9")
        self._set_card_value("1|queries_1|column_name", "c9")
        self._set_card_value("1|cond|min", "5")
        self.screenshot("exposed_step_params_cards")

        # Removing a card drops the override; the saved value applies.
        self.wait_for_selector_clickable(
            f'{_card("1|queries_1|column_name")} [data-description="remove step parameter"]'
        ).click()
        self.wait_for_selector_absent(_card("1|queries_1|column_name"))

        self.workflow_run_submit()
        invocation_id = self._new_invocation_id(history_id, set())
        self.workflow_populator.wait_for_invocation_and_jobs(history_id, None, invocation_id)
        echo = self._echo(history_id, invocation_id)
        assert echo["threshold"] == "0.9", echo
        assert echo["cond.min"] == "5", echo
        assert echo["queries_1.column_name"] == "c2", echo
        request = self.workflow_populator.invocation_to_request(invocation_id)
        assert request["exposed_step_parameters"] == ["1|threshold", "1|cond|min"], request
        assert _as_strings(request["parameters"]) == {"1": {"threshold": "0.9", "cond|min": "5"}}, request

    @selenium_test
    @managed_history
    def test_rerun_reshows_exposed_step_parameters(self):
        history_id = self.current_history_id()
        hda = self._table(history_id)
        workflow_id = self.workflow_populator.upload_yaml_workflow(WORKFLOW_EXPOSED_STEP_PARAMS)
        invocation_id = self._run_api(
            history_id,
            workflow_id,
            hda["id"],
            parameters={"1": {"threshold": 0.75, "cond|min": 3}},
            parameters_normalized=True,
            exposed_step_parameters=["1|threshold", "1|cond|min"],
        )
        self.get(f"workflows/rerun?invocation_id={invocation_id}")
        self._assert_card_value("1|threshold", "0.75")
        self._assert_card_value("1|cond|min", "3")
        self.components.workflow_run.expanded_form.assert_absent()
        self.screenshot("exposed_step_params_rerun_prefilled")

        self.workflow_run_submit()
        rerun_id = self._new_invocation_id(history_id, {invocation_id})
        request = self.workflow_populator.invocation_to_request(rerun_id)
        assert request["exposed_step_parameters"] == ["1|threshold", "1|cond|min"], request
        assert _as_strings(request["parameters"]) == {"1": {"threshold": "0.75", "cond|min": "3"}}, request

    @selenium_test
    @managed_history
    def test_rerun_without_exposed_keys_stays_expanded(self):
        history_id = self.current_history_id()
        hda = self._table(history_id)
        workflow_id = self.workflow_populator.upload_yaml_workflow(WORKFLOW_EXPOSED_STEP_PARAMS)
        invocation_id = self._run_api(
            history_id,
            workflow_id,
            hda["id"],
            parameters={"1": {"threshold": 0.75}},
            parameters_normalized=True,
        )
        self.get(f"workflows/rerun?invocation_id={invocation_id}")
        self.components.workflow_run.expanded_form.wait_for_visible()
        self.screenshot("exposed_step_params_rerun_unrecorded_expanded")

    @selenium_test
    @managed_history
    def test_rerun_with_this_changed(self):
        history_id = self.current_history_id()
        hda = self._table(history_id)
        workflow_id = self.workflow_populator.upload_yaml_workflow(WORKFLOW_EXPOSED_STEP_PARAMS)
        invocation_id = self._run_api(history_id, workflow_id, hda["id"])
        self.get(f"workflows/invocations/{invocation_id}")
        invocations = self.components.invocations
        invocations.invocation_tab(label="Steps").wait_for_and_click()
        invocations.step_details(order_index="1").wait_for_and_click()
        link = self.wait_for_selector_visible(
            '[data-description="rerun with this changed"][data-parameter-name="cond|min"]'
        )
        self.scroll_into_view(link)
        self.sleep_for(self.wait_types.UX_RENDER)
        self.screenshot("exposed_step_params_invocation_rerun_with_this_changed")
        # The conditional's test param and the data-dependent column are not offered.
        self.wait_for_selector_absent(
            '[data-description="rerun with this changed"][data-parameter-name="cond|filter_type"]'
        )
        self.wait_for_selector_absent('[data-description="rerun with this changed"][data-parameter-name="column"]')
        link.click()

        self._assert_card_value("1|cond|min", "1")
        self.components.workflow_run.expanded_form.assert_absent()
        self.screenshot("exposed_step_params_rerun_with_this_changed_form")
        self._set_card_value("1|cond|min", "4")
        self.workflow_run_submit()
        rerun_id = self._new_invocation_id(history_id, {invocation_id})
        self.workflow_populator.wait_for_invocation_and_jobs(history_id, None, rerun_id)
        assert self._echo(history_id, rerun_id)["cond.min"] == "4"

    @selenium_test
    @managed_history
    def test_step_param_link_with_preset_and_unknown_key(self):
        history_id = self.current_history_id()
        self._table(history_id)
        workflow_id = self.workflow_populator.upload_yaml_workflow(WORKFLOW_EXPOSED_STEP_PARAMS)
        self.get(
            f"workflows/run?id={workflow_id}"
            "&step_param=1|cond|min&step_param_value=1|cond|min=7"
            "&step_param=1|cond|pattern&step_param=1|column"
        )
        self._assert_card_value("1|cond|min", "7")
        warning = self.wait_for_selector_visible('[data-description="dropped step parameters"]')
        assert "1|cond|pattern" in warning.text, warning.text
        assert "1|column" in warning.text, warning.text
        self.screenshot("exposed_step_params_link_preset_and_dropped")
