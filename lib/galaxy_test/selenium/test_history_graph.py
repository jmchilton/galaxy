from .framework import (
    selenium_test,
    SeleniumTestCase,
)


class TestHistoryGraph(SeleniumTestCase):
    ensure_registered = True

    @selenium_test
    def test_tool_execution_job_pager(self):
        history_id = self.current_history_id()
        hdas = [self.dataset_populator.new_dataset(history_id, content=f"{i}\n", wait=True) for i in range(3)]
        batch = {"__class__": "Batch", "values": [{"src": "hda", "id": hda["id"]} for hda in hdas]}
        response = self.dataset_populator.tool_request_raw("cat1", {"input1": batch}, history_id)
        response.raise_for_status()
        assert self.dataset_populator.wait_on_tool_request(response.json()["tool_request_id"])

        self.get(f"histories/{history_id}/graph/tool-requests")
        tool_executions = self.components.history_graph.tool_executions
        tool_executions.execution_header.wait_for_and_click()
        tool_executions.current_page(page=1).wait_for_visible()
        tool_executions.page_button(page=3).wait_for_and_click()
        tool_executions.current_page(page=3).wait_for_visible()
        self.screenshot("history_graph_tool_execution_job_pager")
