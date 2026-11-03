from galaxy_test.base.workflow_fixtures import (
    WORKFLOW_KEEP_SUCCESSFUL_DATASETS,
    WORKFLOW_KEEP_SUCCESSFUL_DATASETS_TEST_DATA,
)
from .framework import (
    managed_history,
    retry_assertion_during_transitions,
    selenium_test,
    SeleniumTestCase,
)

# Two independent input -> cat branches, so selecting a step on one branch isolates it from the other.
WORKFLOW_TWO_BRANCHES = """
class: GalaxyWorkflow
inputs:
  left_input:
    type: data
    position: {left: 0, top: 0}
  right_input:
    type: data
    position: {left: 0, top: 200}
steps:
  left_cat:
    tool_id: cat1
    position: {left: 300, top: 0}
    in:
      input1: left_input
  right_cat:
    tool_id: cat1
    position: {left: 300, top: 200}
    in:
      input1: right_input
test_data:
  left_input: |
    left
  right_input: |
    right
"""
TWO_BRANCHES_LABELS = ["left_input", "right_input", "left_cat", "right_cat"]

# A table branch, an image copy, a text split into a collection and a two-output step; six workflow outputs.
WORKFLOW_OUTPUT_KINDS = """
class: GalaxyWorkflow
name: Output previews
inputs:
  table:
    type: data
    position: {left: 0, top: 0}
  image:
    type: data
    position: {left: 0, top: 220}
  text:
    type: data
    position: {left: 0, top: 420}
outputs:
  top_rows:
    outputSource: head_table/out_file1
  summary:
    outputSource: head_cat/out_file1
  plot:
    outputSource: copy_image/out_file1
  lines:
    outputSource: split_text/output
  numbers_b:
    outputSource: numbers/output_b
  final_table:
    outputSource: final/out_file1
steps:
  head_table:
    tool_id: head
    position: {left: 260, top: 0}
    in:
      input: table
    state:
      lineNum: 5
  cat_table:
    tool_id: cat
    position: {left: 260, top: 110}
    in:
      input1: table
  head_cat:
    tool_id: head
    position: {left: 520, top: 110}
    in:
      input: cat_table/out_file1
    state:
      lineNum: 8
  copy_image:
    tool_id: cat
    position: {left: 260, top: 230}
    in:
      input1: image
  split_text:
    tool_id: split
    position: {left: 260, top: 420}
    in:
      input1: text
  numbers:
    tool_id: output_order
    position: {left: 520, top: 420}
    state:
      pa: 3
      pb: 4
  final:
    tool_id: cat
    position: {left: 780, top: 50}
    in:
      input1: head_cat/out_file1
      queries_0|input2: head_table/out_file1
test_data:
  table:
    value: 2.tabular
    name: measurements
    type: File
    file_type: tabular
  image:
    value: 454Score.png
    name: quality plot
    type: File
    file_type: png
  text:
    value: simple_line_x2.txt
    name: two lines
    type: File
    file_type: txt
"""
OUTPUT_KINDS_LABELS = [
    "table",
    "image",
    "text",
    "head_table",
    "cat_table",
    "head_cat",
    "copy_image",
    "split_text",
    "numbers",
    "final",
]


class TestWorkflowInvocationGraph(SeleniumTestCase):
    ensure_registered = True

    @selenium_test
    @managed_history  # the failed job would trip history waits that assert every dataset is ok
    def test_failed_step_is_marked(self):
        self.workflow_populator.run_workflow(
            WORKFLOW_KEEP_SUCCESSFUL_DATASETS,
            test_data=WORKFLOW_KEEP_SUCCESSFUL_DATASETS_TEST_DATA,
            history_id=self.current_history_id(),
            assert_ok=False,
        )
        self.invocation_open_latest()
        invocations = self.components.invocations
        invocations.graph_node_state(label="mixed_collection", state="error").wait_for_present()
        # Only the step with the failed job is marked, not the steps downstream of it.
        invocations.graph_node_state(label="cat", state="ok").wait_for_present()
        self._wait_for_polling_to_stop()
        self.screenshot("invocation_graph_failed_step")

    @selenium_test
    def test_step_card_navigation(self):
        self._open_two_branches_invocation()
        invocations = self.components.invocations

        invocations.step_card.assert_absent()
        self._click_node("left_cat")
        self._assert_step_card_title("left_cat")
        invocations.step_card_icon(icon="wrench").wait_for_visible()
        self.screenshot("invocation_graph_step_card")

        invocations.step_card_next.wait_for_and_click()
        self._assert_step_card_title("right_cat")
        invocations.step_card_previous.wait_for_and_click()
        self._assert_step_card_title("left_cat")
        invocations.step_card_previous.wait_for_and_click()
        self._assert_step_card_title("right_input")
        invocations.step_card_icon(icon="file").wait_for_visible()

        invocations.step_card_hide.wait_for_and_click()
        invocations.step_card.wait_for_absent()

    @selenium_test
    def test_isolate_selected_step_lineage(self):
        self._open_two_branches_invocation()
        invocations = self.components.invocations
        for label in TWO_BRANCHES_LABELS:
            invocations.graph_node_out_of_focus(label=label).assert_absent()

        self._click_node("left_cat")
        invocations.graph_node_out_of_focus(label="right_input").wait_for_present()
        invocations.graph_node_out_of_focus(label="right_cat").wait_for_present()
        invocations.graph_node_out_of_focus(label="left_input").assert_absent()
        invocations.graph_node_out_of_focus(label="left_cat").assert_absent()
        self.sleep_for(self.wait_types.UX_RENDER)  # let the 0.2s dimming opacity transition finish
        self.screenshot("invocation_graph_isolated_step")

    @selenium_test
    def test_show_connections(self):
        self._open_two_branches_invocation()
        left_cat = self.components.workflow_editor.node._(label="left_cat")
        self._click_node("left_cat")
        self._assert_output_terminal_blank("left_cat", "out_file1", blank=True)
        assert "out_file1" not in left_cat.wait_for_visible().text

        toggle = self.components.invocations.graph_show_connections_button
        toggle.wait_for_and_click()
        self._assert_output_terminal_blank("left_cat", "out_file1", blank=False)
        left_cat_text = left_cat.wait_for_visible().text
        assert "out_file1" in left_cat_text
        assert "Concatenate Dataset" in left_cat_text
        # Only the active step is drawn with connections.
        self._assert_output_terminal_blank("right_cat", "out_file1", blank=True)
        self.screenshot("invocation_graph_show_connections")

        toggle.wait_for_and_click()
        self._assert_output_terminal_blank("left_cat", "out_file1", blank=True)

    @selenium_test
    def test_step_config_is_read_only(self):
        self._open_two_branches_invocation()
        invocations = self.components.invocations
        self._click_node("left_cat")
        invocations.step_card_config_tab.wait_for_and_click()
        invocations.step_card_config_form.wait_for_visible()
        label_input = self.components.workflow_editor.label_input.wait_for_visible()
        self.scroll_into_view(label_input)
        self.screenshot("invocation_graph_step_config")
        assert label_input.get_attribute("value") == "left_cat"
        assert not label_input.is_enabled()

    @selenium_test
    def test_expand_step_to_modal(self):
        self._open_two_branches_invocation()
        invocations = self.components.invocations
        self._click_node("left_cat")
        invocations.step_card_body_config_tab.wait_for_visible()

        invocations.step_card_expand.wait_for_and_click()
        invocations.step_card_modal.wait_for_visible()
        invocations.step_card_modal_config_tab.wait_for_visible()
        invocations.step_card_body_config_tab.assert_absent()
        self.screenshot("invocation_graph_step_expanded")

        invocations.step_card_modal_close.wait_for_and_click()
        invocations.step_card_modal.wait_for_absent()
        invocations.step_card_body_config_tab.wait_for_visible()

    @selenium_test
    def test_search_selects_step(self):
        self._open_two_branches_invocation()
        invocations = self.components.invocations
        invocations.graph_search_toggle.wait_for_and_click()
        invocations.graph_search_input.wait_for_and_send_keys("right_cat")

        @retry_assertion_during_transitions
        def assert_single_result():
            results = invocations.graph_search_result.all()
            assert [result.text.strip() for result in results] == ["4: right_cat"]

        assert_single_result()
        self.screenshot("invocation_graph_search")
        invocations.graph_search_result.wait_for_and_click()
        self._assert_step_card_title("right_cat")

    @selenium_test
    def test_hover_previews_step_outputs(self):
        self._open_output_kinds_invocation()
        self.screenshot("invocation_graph_output_kinds")

        # a workflow output, listed with its label
        output = self._hover_outputs("head_table", "out_file1")
        assert output.label.wait_for_text() == "top_rows"
        output.table.wait_for_visible()
        rows = output.table_row.all()
        assert len(rows) == 5  # head -n 5
        assert rows[0].text.split() == ["1", "68", "4.1"]  # 2.tabular's first row
        self.screenshot("invocation_graph_output_preview_table")

        # not a workflow output: the step's details are fetched on hover, and it's listed by output name
        output = self._hover_outputs("cat_table", "out_file1")
        assert output.label.wait_for_text() == "out_file1"
        output.table.wait_for_visible()
        assert len(output.table_row.all()) == 10  # all of 2.tabular

        output = self._hover_outputs("copy_image", "out_file1")
        self._wait_for_image_loaded(output.image.wait_for_visible())
        self.screenshot("invocation_graph_output_preview_image")

        # a collection, previewed with its elements
        output = self._hover_outputs("split_text", "output")
        assert output.label.wait_for_text() == "lines"
        output.collection_element_name.wait_for_visible()
        assert [element.text for element in output.collection_element_name.all()] == ["1", "2"]  # one per line
        self.screenshot("invocation_graph_output_preview_collection")

        # every output of a multi-output step
        output_a = self._hover_outputs("numbers", "output_a")
        output_b = self.components.invocations.graph_step_output._(name="output_b")
        assert output_a.text.wait_for_text().strip() == "3"
        assert output_b.label.wait_for_text() == "numbers_b"
        assert output_b.text.wait_for_text().strip() == "4"
        self.screenshot("invocation_graph_output_preview_multiple_outputs")

    def _open_output_kinds_invocation(self) -> None:
        self._open_invocation(WORKFLOW_OUTPUT_KINDS, OUTPUT_KINDS_LABELS)
        # the pointer is still on the activity that closed the invocations panel; move it off that tooltip
        self.clear_tooltips()
        self.components.invocations.activity_tooltip.wait_for_absent_or_hidden()
        # and drop the focus that click left there, so screenshots and Escape presses don't draw a focus ring on it
        self._drop_focus()

    def _drop_focus(self) -> None:
        self.execute_script("document.activeElement.blur();")

    def _hover_outputs(self, label: str, output_name: str):
        """Hover the step's output terminals, wait for its output previews to load and return the named one"""
        invocations = self.components.invocations
        # moving away could land on the open popover, which keeps it open; Escape dismisses it
        self.send_escape()
        invocations.graph_step_outputs.wait_for_absent_or_hidden()
        terminal = self.components.workflow_editor.node._(label=label).output_terminal(name=output_name)
        self.hover(terminal.wait_for_present())
        output = invocations.graph_step_output._(name=output_name)
        output.wait_for_visible()
        # covers both the popover's own loading message and each preview's dataset or collection loading
        invocations.graph_step_outputs_loading.wait_for_absent()
        return output

    def _wait_for_image_loaded(self, image):
        # a visible <img> may still be decoding; wait so the screenshot shows the picture at its final size
        self._wait_on(
            lambda: self.execute_script("return arguments[0].complete && arguments[0].naturalWidth > 0;", image),
            "output preview image to load",
            wait_type=self.wait_types.UX_TRANSITION,
        )

    def _open_invocation(self, workflow: str, labels: list[str]):
        self.workflow_populator.run_workflow(workflow, history_id=self.current_history_id())
        self.invocation_open_latest()
        timeout = self.wait_length(self.wait_types.JOB_COMPLETION)
        for label in labels:
            self.components.invocations.graph_node_state(label=label, state="ok").wait_for_present(timeout=timeout)
        self._wait_for_polling_to_stop()

    def _open_two_branches_invocation(self):
        self._open_invocation(WORKFLOW_TWO_BRANCHES, TWO_BRANCHES_LABELS)

    def _wait_for_polling_to_stop(self):
        # The graph keeps re-rendering until job polling ends; settle it before clicking or screenshotting.
        self.components.invocations.polling_indicator.wait_for_absent(wait_type=self.wait_types.JOB_COMPLETION)

    def _click_node(self, label: str):
        self.components.workflow_editor.node._(label=label).title.wait_for_and_click()

    @retry_assertion_during_transitions
    def _assert_step_card_title(self, label: str):
        title = self.components.invocations.step_card_title.wait_for_visible().text
        assert label in title, f"Expected step card for {label}, found {title!r}"

    @retry_assertion_during_transitions
    def _assert_output_terminal_blank(self, label: str, output_name: str, blank: bool):
        terminal = self.components.workflow_editor.node._(label=label).output_terminal(name=output_name)
        terminal.wait_for_present()
        assert terminal.has_class("blank-output") == blank, f"Expected {label} {output_name} blank={blank}"
