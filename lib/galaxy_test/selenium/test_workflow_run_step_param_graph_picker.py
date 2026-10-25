"""Spike: picking step parameters for the simple run form from the workflow graph."""

from galaxy_test.base.workflow_fixtures import WORKFLOW_EXPOSED_STEP_PARAMS_GRAPH
from .framework import (
    managed_history,
    retry_assertion_during_transitions,
    RunsWorkflows,
    selenium_test,
    SeleniumTestCase,
)

PICKER = '[data-description="step parameter graph picker"]'
PANEL = '[data-description="graph picker step panel"]'
PICKER_OK = ".g-modal-confirm-buttons button:last-child"


def _card(key: str) -> str:
    return f'.step-parameter-card[data-exposure-key="{key}"]'


def _node(order_index: int) -> str:
    return f"{PICKER} #wf-node-step-{order_index}"


class TestWorkflowRunStepParamGraphPicker(SeleniumTestCase, RunsWorkflows):
    ensure_registered = True

    def _echo(self, history_id: str, invocation_id: str) -> dict[str, str]:
        invocation = self.workflow_populator.get_invocation(invocation_id)
        content = self.dataset_populator.get_history_dataset_content(
            history_id, dataset_id=invocation["outputs"]["echo"]["id"]
        )
        return dict(line.split("=", 1) for line in content.splitlines() if line)

    @retry_assertion_during_transitions
    def _invocation_id(self, history_id: str) -> str:
        invocations = self.workflow_populator.history_invocations(history_id, include_nested_invocations=False)
        assert len(invocations) == 1, invocations
        return invocations[0]["id"]

    def _open_picker(self):
        self.wait_for_selector_clickable('[data-description="pick step parameters from graph"]').click()
        self.wait_for_selector_visible(_node(1))

    def _click_node(self, order_index: int):
        self.wait_for_selector_clickable(f"{_node(order_index)} .node-title").click()

    def _toggle(self, key: str):
        self.wait_for_selector_clickable(f'{PANEL} label[data-exposure-key="{key}"] input').click()

    @retry_assertion_during_transitions
    def _assert_node_text(self, order_index: int, expected: str):
        text = self.wait_for_selector_visible(_node(order_index)).text
        assert expected in text, text

    @selenium_test
    @managed_history
    def test_pick_from_graph_deselect_and_run(self):
        history_id = self.current_history_id()
        self.dataset_populator.new_dataset(history_id, content="1\t2\t3\n", file_type="tabular", wait=True)
        self.workflow_run_open_workflow(WORKFLOW_EXPOSED_STEP_PARAMS_GRAPH)
        self._open_picker()
        self._assert_node_text(2, "can't be picked here")
        self.screenshot("graph_picker_overview")

        self._click_node(1)
        self._toggle("1|threshold")
        self._toggle("1|cond|min")
        self._assert_node_text(1, "2 of")
        self.screenshot("graph_picker_step_picked")

        self._click_node(2)
        self.wait_for_selector_visible('[data-description="graph picker subworkflow locked"]')
        self.wait_for_selector_absent(f"{PANEL} label[data-exposure-key]")
        self.screenshot("graph_picker_subworkflow_locked")
        self.wait_for_selector_clickable(PICKER_OK).click()
        self.wait_for_selector_visible(_card("1|threshold"))
        self.wait_for_selector_visible(_card("1|cond|min"))
        self.screenshot("graph_picker_cards")

        # Deselecting in the graph removes the card.
        self._open_picker()
        self._click_node(1)
        self._toggle("1|threshold")
        self.wait_for_selector_clickable(PICKER_OK).click()
        self.wait_for_selector_absent(_card("1|threshold"))
        field = self.wait_for_selector_visible(f"{_card('1|cond|min')} .ui-input")
        field.clear()
        field.send_keys("5")

        self.workflow_run_submit()
        invocation_id = self._invocation_id(history_id)
        self.workflow_populator.wait_for_invocation_and_jobs(history_id, None, invocation_id)
        echo = self._echo(history_id, invocation_id)
        assert echo["cond.min"] == "5", echo
        assert echo["threshold"] == "0.5", echo
        request = self.workflow_populator.invocation_to_request(invocation_id)
        assert request["exposed_step_parameters"] == ["1|cond|min"], request

    @selenium_test
    @managed_history
    def test_link_subworkflow_key_is_dropped_with_warning(self):
        history_id = self.current_history_id()
        self.dataset_populator.new_dataset(history_id, content="1\t2\t3\n", file_type="tabular", wait=True)
        workflow_id = self.workflow_populator.upload_yaml_workflow(WORKFLOW_EXPOSED_STEP_PARAMS_GRAPH)
        self.get(
            f"workflows/run?id={workflow_id}"
            "&step_param=1|cond|min&step_param_value=1|cond|min=7"
            "&step_param=2|1|threshold&step_param_value=2|1|threshold=0.9"
        )
        self.wait_for_selector_visible(_card("1|cond|min"))
        warning = self.wait_for_selector_visible('[data-description="dropped subworkflow step parameters"]')
        assert "2|1|threshold" in warning.text, warning.text
        self.screenshot("graph_picker_link_subworkflow_dropped")

        self._open_picker()
        banner = self.wait_for_selector_visible('[data-description="graph picker locked subworkflow parameters"]')
        assert "2|1|threshold" in banner.text, banner.text
        assert "not sent" in self.wait_for_selector_visible(PICKER_OK).text
        self.screenshot("graph_picker_locked_banner")
        self.wait_for_selector_clickable(PICKER_OK).click()

        self.workflow_run_submit()
        invocation_id = self._invocation_id(history_id)
        request = self.workflow_populator.invocation_to_request(invocation_id)
        assert request["exposed_step_parameters"] == ["1|cond|min"], request
        assert {k: {n: str(v) for n, v in p.items()} for k, p in request["parameters"].items()} == {
            "1": {"cond|min": "7"}
        }, request
