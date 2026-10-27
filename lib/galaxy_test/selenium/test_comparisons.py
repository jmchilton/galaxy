from .framework import (
    retry_assertion_during_transitions,
    selenium_test,
    SeleniumTestCase,
)

WORKFLOW_TWO_CAT = """
class: GalaxyWorkflow
inputs:
  input1: data
outputs:
  first_out:
    outputSource: first_cat/out_file1
  second_out:
    outputSource: second_cat/out_file1
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

WORKFLOW_MAPPED_CAT = """
class: GalaxyWorkflow
inputs:
  input_list:
    type: collection
    collection_type: list
steps:
  mapped_cat:
    tool_id: cat1
    in:
      input1: input_list
test_data:
  input_list:
    collection_type: list
    elements:
      - identifier: el0
        content: "a"
      - identifier: el1
        content: "b"
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
        self._screenshot_settled("comparisons_step_all_runs_row_detail", comparisons.row_detail_changed_parameter)
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
        self._assert_comparison_page("step_runs")
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
        comparisons.compare_outputs_button.wait_for_visible()
        self._assert_invocation_grid_rows(3)
        self.screenshot("comparisons_stored_workflow_invocations")
        comparisons.compare_outputs_button.wait_for_and_click()
        self._assert_comparison_page("output_runs")
        self._assert_rows(newest_id, *older_ids)
        self.screenshot("comparisons_compare_outputs_page")

        comparisons.column_header(key="output:first_out").wait_for_visible()
        comparisons.output_filter(label="second_out").wait_for_and_click()
        self.assert_current_url_contains("output_labels=second_out")
        comparisons.column_header(key="output:first_out").wait_for_absent()
        comparisons.column_header(key="output:second_out").wait_for_visible()
        comparisons.column_header(key="input:input1").wait_for_visible()

        comparisons.state_filter(state="failed").wait_for_and_click()
        self.assert_current_url_contains("states=failed")
        self._assert_empty("No runs match these filters.")
        assert len(comparisons.rows.all()) == 0

        steps = self.workflow_populator.get_invocation(newest_id, step_details=True)["steps"]
        (second_cat,) = [step for step in steps if step["workflow_step_label"] == "second_cat"]
        job_id = second_cat["jobs"][0]["id"]
        self.get(f"jobs/{job_id}/view")
        self._screenshot_settled("comparisons_job_other_runs_action", comparisons.other_runs_action)
        comparisons.other_runs_action.wait_for_and_click()
        self._assert_comparison_page("tool_runs")
        comparisons.row(run_id=job_id).wait_for_visible()
        self.screenshot("comparisons_tool_runs_page")

        self.get(f"datasets/{second_cat['outputs']['out_file1']['id']}/details")
        self._screenshot_settled("comparisons_dataset_details_other_runs_action", comparisons.other_runs_action)
        comparisons.other_runs_action.wait_for_and_click()
        self._assert_comparison_page("tool_runs")
        comparisons.row(run_id=job_id).wait_for_visible()

        self.get(f"workflows/edit?id={workflow_id}")
        self.workflow_editor_ensure_tool_form_open("second_cat")
        comparisons.editor_compare_runs_link.wait_for_visible()
        self.screenshot("comparisons_editor_compare_runs_link")
        comparisons.editor_compare_runs_link.wait_for_and_click()
        self._assert_comparison_page("step_runs")
        self.assert_current_url_contains("step_label=second_cat")
        self._assert_rows(newest_id, *older_ids)

    @selenium_test
    def test_mapped_step_reused_job(self):
        summary = self.workflow_populator.run_workflow(WORKFLOW_MAPPED_CAT, history_id=self.current_history_id())
        reused_id = self.workflow_populator.invoke_workflow_and_wait(
            summary.workflow_id, request={**summary.workflow_request, "use_cached_job": True}
        ).json()["id"]
        # a job cache miss would otherwise only show as a timeout waiting for the reused badge
        self._assert_jobs_reused(reused_id, count=2)
        self.get(f"comparisons?kind=step_runs&workflow_id={summary.workflow_id}&step_label=mapped_cat")

        comparisons = self.components.comparisons
        self._assert_rows(reused_id, summary.invocation_id)
        comparisons.row_expand(run_id=reused_id).wait_for_and_click()
        self._screenshot_settled("comparisons_mapped_step_reused_job", comparisons.row_detail_reused_badge)
        comparisons.row_expand(run_id=reused_id).wait_for_and_click()
        comparisons.row_detail.wait_for_absent_or_hidden()

        comparisons.row_expand(run_id=summary.invocation_id).wait_for_and_click()
        comparisons.row_detail.wait_for_visible()
        comparisons.row_detail_job_pager.wait_for_visible()
        comparisons.row_detail_reused_badge.assert_absent()

        # on a table narrower than its columns, the detail's pager stays in view at either scroll end
        self.execute_script(f"document.querySelector('{comparisons._.selector}').style.width = '400px';")
        self._assert_table_overflows(times=2)
        for scroll in ("0", "scroller.scrollWidth"):
            self.execute_script(
                f"const scroller = document.querySelector('{comparisons.table_scroller.selector}');"
                f"scroller.scrollLeft = {scroll};"
            )
            self._assert_within_table_scroller(comparisons.row_detail_job_pager)

    def _runs_across_two_versions(self) -> tuple[str, list[str], str]:
        """Two runs of v1, then a rename makes v2 and it runs once more."""
        summary = self.workflow_populator.run_workflow(
            WORKFLOW_TWO_CAT, history_id=self.current_history_id(), invocations=2
        )
        workflow_id = summary.workflow_id
        older_ids = [invocation["id"] for invocation in self.workflow_populator.workflow_invocations(workflow_id)]
        self.workflow_populator.rename_workflow(workflow_id, "two cats v2")
        newest_id = self.workflow_populator.invoke_workflow_and_wait(
            workflow_id, request=summary.workflow_request
        ).json()["id"]
        assert len(older_ids) == 2 and newest_id not in older_ids
        return workflow_id, older_ids, newest_id

    def _assert_jobs_reused(self, invocation_id: str, count: int):
        jobs = self.dataset_populator.invocation_jobs(invocation_id)
        assert len(jobs) == count, jobs
        for job in jobs:
            details = self.dataset_populator.get_job_details(job["id"], full=True).json()
            assert details["copied_from_job_id"], f"Expected the job cache to reuse a job: {details}"

    def _screenshot_settled(self, label: str, subject):
        """Screenshot with subject in view, once loading spinners are gone and fade-ins have run."""
        self._wait_on(
            lambda: not any(
                span.is_displayed() for span in self.find_elements_by_selector('[data-description="loading message"]')
            ),
            "visible loading messages to clear",
            wait_type=self.wait_types.DATABASE_OPERATION,
        )
        self.sleep_for(self.wait_types.UX_RENDER)
        self.scroll_into_view(subject.wait_for_visible())
        self.screenshot(label)

    def _assert_comparison_page(self, kind: str):
        self.components.comparisons._.wait_for_visible()
        self.assert_current_url_contains(f"kind={kind}")

    def _assert_rows(self, *run_ids: str):
        comparisons = self.components.comparisons
        for run_id in run_ids:
            comparisons.row(run_id=run_id).wait_for_visible()
        assert len(comparisons.rows.all()) == len(run_ids)

    @retry_assertion_during_transitions
    def _assert_invocation_grid_rows(self, count: int):
        rows = self.find_elements_by_selector('.grid-table [data-description="grid item"]')
        assert len(rows) == count, f"Expected {count} invocation rows, found {len(rows)}"

    @retry_assertion_during_transitions
    def _assert_table_overflows(self, times: int):
        widths = self.execute_script(
            f"const scroller = document.querySelector('{self.components.comparisons.table_scroller.selector}');"
            "return {scroll: scroller.scrollWidth, client: scroller.clientWidth};"
        )
        assert widths["scroll"] > times * widths["client"], widths

    @retry_assertion_during_transitions
    def _assert_within_table_scroller(self, component):
        rects = self.execute_script(
            "const rect = (selector) => document.querySelector(selector).getBoundingClientRect();"
            f"const outer = rect('{self.components.comparisons.table_scroller.selector}');"
            f"const inner = rect('{component.selector}');"
            "return {outer: [outer.left, outer.right], inner: [inner.left, inner.right]};"
        )
        assert rects["outer"][0] <= rects["inner"][0] and rects["inner"][1] <= rects["outer"][1], rects

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
