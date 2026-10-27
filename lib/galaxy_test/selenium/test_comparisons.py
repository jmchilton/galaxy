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
        self.invocation_graph_wait_for_polling_to_stop()
        self.invocation_graph_click_node("second_cat")
        self.assert_invocation_step_card_title("second_cat")

        comparisons = self.components.comparisons
        comparisons.step_all_runs_tab.wait_for_and_click()
        self._assert_rows(newest_id, *older_ids)
        assert "v2" in comparisons.row(run_id=newest_id).wait_for_visible().text
        assert "v1" in comparisons.row(run_id=older_ids[0]).wait_for_visible().text
        self.screenshot("comparisons_step_all_runs")

        # an older run's details diff its job's parameters against the viewed run's
        comparisons.row_expand(run_id=older_ids[0]).wait_for_and_click()
        comparisons.row_detail.wait_for_visible()
        changed = comparisons.row_detail_changed_parameter.wait_for_visible()
        assert "Concatenate Dataset" in changed.text, changed.text
        self.screenshot("comparisons_step_all_runs_row_detail")
        comparisons.row_expand(run_id=older_ids[0]).wait_for_and_click()
        comparisons.row_detail.wait_for_absent_or_hidden()

        comparisons.row_select(run_id=newest_id).wait_for_and_click()
        comparisons.row_select(run_id=older_ids[0]).wait_for_and_click()
        comparisons.compare_selected.wait_for_and_click()
        comparisons.diff_panel.wait_for_visible()
        version_line = comparisons.diff_changed_line(key="version").wait_for_visible()
        assert "v2" in version_line.text and "v1" in version_line.text, version_line.text
        self.screenshot("comparisons_step_all_runs_diff")
        comparisons.compare_selected.wait_for_and_click()
        comparisons.diff_panel.wait_for_absent_or_hidden()

        comparisons.transpose_toggle.wait_for_and_click()
        self._assert_transposed(True)
        assert len(comparisons.transposed_run_links.all()) == 3
        comparisons.row(run_id=newest_id).assert_absent()
        self.screenshot("comparisons_step_all_runs_transposed")
        comparisons.transpose_toggle.wait_for_and_click()
        self._assert_transposed(False)
        comparisons.row(run_id=newest_id).wait_for_visible()

        comparisons.view_all_link.wait_for_and_click()
        comparisons._.wait_for_visible()
        self.assert_current_url_contains("kind=step_runs")
        self._assert_rows(newest_id, *older_ids)
        self._assert_summary("Showing 1–3 of 3 · newest first · your runs only")

        # On dev the invocation view ignores ?step_label= until #24173 lands; only check we land on the run.
        comparisons.row_link(run_id=older_ids[0]).wait_for_and_click()
        self.assert_current_url_contains(f"/workflows/invocations/{older_ids[0]}")

    @selenium_test
    def test_comparison_pages_from_entry_points(self):
        workflow_id, older_ids, newest_id = self._runs_across_two_versions()
        self.get(f"workflows/{workflow_id}/invocations")
        comparisons = self.components.comparisons
        comparisons.compare_outputs_button.wait_for_and_click()
        comparisons._.wait_for_visible()
        self._assert_rows(newest_id, *older_ids)
        self.assert_current_url_contains("kind=output_runs")
        self.screenshot("comparisons_compare_outputs_page")

        comparisons.state_filter(state="failed").wait_for_and_click()
        self.assert_current_url_contains("states=failed")
        self._assert_empty("No runs match these filters.")
        assert len(comparisons.rows.all()) == 0

        steps = self.workflow_populator.get_invocation(newest_id, step_details=True)["steps"]
        (second_cat,) = [step for step in steps if step["workflow_step_label"] == "second_cat"]
        job_id = second_cat["jobs"][0]["id"]
        self.get(f"jobs/{job_id}/view")
        comparisons.other_runs_action.wait_for_and_click()
        self.assert_current_url_contains("kind=tool_runs")
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

    def _assert_rows(self, *run_ids: str):
        comparisons = self.components.comparisons
        for run_id in run_ids:
            comparisons.row(run_id=run_id).wait_for_visible()
        assert len(comparisons.rows.all()) == len(run_ids)

    @retry_assertion_during_transitions
    def _assert_transposed(self, transposed: bool):
        pressed = self.components.comparisons.transpose_toggle.wait_for_visible().get_attribute("aria-pressed")
        assert pressed == ("true" if transposed else "false"), f"Expected transposed={transposed}, got {pressed!r}"

    @retry_assertion_during_transitions
    def _assert_empty(self, message: str):
        text = self.components.comparisons.empty_message.wait_for_visible().text
        assert text.strip() == message, f"Expected {message!r}, found {text!r}"

    @retry_assertion_during_transitions
    def _assert_summary(self, summary: str):
        text = self.components.comparisons.summary.wait_for_visible().text
        assert text.strip() == summary, f"Expected {summary!r}, found {text!r}"
