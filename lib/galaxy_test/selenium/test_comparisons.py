from .framework import (
    retry_assertion_during_transitions,
    selenium_test,
    SeleniumTestCase,
)

WORKFLOW_TWO_CAT = """
class: GalaxyWorkflow
inputs:
  input1: data
steps:
  first_cat:
    tool_id: cat1
    in:
      input1: input1
  second_cat:
    tool_id: cat1
    in:
      input1: first_cat/out_file1
test_data:
  input1: "hello world"
"""


class TestComparisons(SeleniumTestCase):
    ensure_registered = True

    @selenium_test
    def test_step_all_runs_across_versions(self):
        workflow_id, older_ids, newest_id = self._runs_across_two_versions()
        self.invocation_open_latest()
        self.components.workflow_editor.node._(label="second_cat").title.wait_for_and_click()
        self._assert_step_card_title("second_cat")

        comparisons = self.components.comparisons
        comparisons.step_all_runs_tab.wait_for_and_click()
        for run_id in [newest_id, *older_ids]:
            comparisons.row(run_id=run_id).wait_for_visible()
        assert len(comparisons.rows.all()) == 3
        assert "v2" in comparisons.row(run_id=newest_id).wait_for_visible().text
        assert "v1" in comparisons.row(run_id=older_ids[0]).wait_for_visible().text
        self.screenshot("comparisons_step_all_runs")

        comparisons.transpose_toggle.wait_for_and_click()
        comparisons.table.wait_for_visible()
        self.screenshot("comparisons_step_all_runs_transposed")
        comparisons.transpose_toggle.wait_for_and_click()

        # On dev the invocation view ignores ?step_label= until #24173 lands; only check we land on the run.
        comparisons.row_link(run_id=older_ids[0]).wait_for_and_click()
        self._assert_url_contains(f"/workflows/invocations/{older_ids[0]}")

    @selenium_test
    def test_comparison_pages_from_entry_points(self):
        workflow_id, older_ids, newest_id = self._runs_across_two_versions()
        self.get(f"workflows/{workflow_id}/invocations")
        comparisons = self.components.comparisons
        comparisons.compare_outputs_button.wait_for_and_click()
        comparisons._.wait_for_visible()
        for run_id in [newest_id, *older_ids]:
            comparisons.row(run_id=run_id).wait_for_visible()
        self._assert_url_contains("kind=output_runs")
        self.screenshot("comparisons_compare_outputs_page")

        comparisons.state_filter(state="failed").wait_for_and_click()
        self._assert_url_contains("states=failed")
        comparisons.row(run_id=newest_id).wait_for_absent()

        job_id = self.workflow_populator.get_invocation(newest_id, step_details=True)["steps"][-1]["jobs"][0]["id"]
        self.get(f"jobs/{job_id}/view")
        comparisons.other_runs_action.wait_for_and_click()
        self._assert_url_contains("kind=tool_runs")
        comparisons.row(run_id=job_id).wait_for_visible()
        self.screenshot("comparisons_tool_runs_page")

    def _runs_across_two_versions(self) -> tuple[str, list[str], str]:
        """Two runs of v1, then a rename makes v2 and it runs once more."""
        summary = self.workflow_populator.run_workflow(
            WORKFLOW_TWO_CAT, history_id=self.current_history_id(), invocations=2
        )
        workflow_id = summary.workflow_id
        older_ids = [invocation["id"] for invocation in self.workflow_populator.workflow_invocations(workflow_id)]
        response = self.workflow_populator.refactor_workflow(
            workflow_id, [{"action_type": "update_name", "name": "two cats v2"}]
        )
        response.raise_for_status()
        newest_id = self.workflow_populator.invoke_workflow_and_wait(
            workflow_id, request=summary.workflow_request
        ).json()["id"]
        assert len(older_ids) == 2 and newest_id not in older_ids
        return workflow_id, older_ids, newest_id

    @retry_assertion_during_transitions
    def _assert_step_card_title(self, label: str):
        title = self.components.invocations.step_card_title.wait_for_visible().text
        assert label in title, f"Expected step card for {label}, found {title!r}"

    @retry_assertion_during_transitions
    def _assert_url_contains(self, fragment: str):
        assert fragment in self.current_url, f"Expected {fragment!r} in {self.current_url!r}"
