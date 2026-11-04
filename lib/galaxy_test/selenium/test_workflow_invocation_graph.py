from typing import (
    Any,
    NamedTuple,
)

from gxformat2 import python_to_workflow
from gxformat2.yaml import ordered_load

from galaxy.selenium.smart_components import SmartComponent
from galaxy.selenium.web_element_protocol import WebElementProtocol
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

# Each workflow output of WORKFLOW_OUTPUT_KINDS and the step producing it
EMBEDDED_OUTPUT_SOURCES = {
    "top_rows": "head_table",
    "summary": "head_cat",
    "plot": "copy_image",
    "lines": "split_text",
    "numbers_b": "numbers",
    "final_table": "final",
}
# Steps of WORKFLOW_OUTPUT_KINDS shown as their preferred output: one of a workflow output (so it gets no card),
# one of an output the invocation doesn't list
PREFERRED_OUTPUTS = {"head_table": "out_file1", "cat_table": "out_file1"}
# The layout puts each card 20 workflow pixels right of its step, so at a zoom of at most 1 it's closer than this.
MAX_CARD_GAP = 30
# Allowance for subpixel rounding when comparing on-screen edges.
EDGE_TOLERANCE = 2


class ClientRect(NamedTuple):
    left: float
    top: float
    right: float
    bottom: float

    def clear_of(self, other: "ClientRect") -> bool:
        """Whether the boxes don't overlap, allowing touching edges to round into each other"""
        return (
            self.right <= other.left + EDGE_TOLERANCE
            or other.right <= self.left + EDGE_TOLERANCE
            or self.bottom <= other.top + EDGE_TOLERANCE
            or other.bottom <= self.top + EDGE_TOLERANCE
        )


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

    @selenium_test
    def test_embed_workflow_outputs(self):
        self._open_output_kinds_invocation()
        invocations = self.components.invocations
        toggle = invocations.graph_embed_outputs_toggle
        assert toggle.wait_for_visible().get_attribute("aria-pressed") == "false"
        authored = self._node_positions()
        self.screenshot("invocation_graph_before_embedding")

        transform = self._graph_transform()
        toggle.wait_for_and_click()
        invocations.graph_embedded_outputs.wait_for_present()
        assert toggle.wait_for_visible().get_attribute("aria-pressed") == "true"
        labels = [card.get_attribute("data-output-label") for card in invocations.graph_embedded_outputs.all()]
        assert sorted(labels) == sorted(EMBEDDED_OUTPUT_SOURCES)
        invocations.graph_embedded_outputs_loading.wait_for_absent()

        # each card previews its output's content; wait for presence, as a card may clip a long table
        embedded_output = invocations.graph_embedded_output
        top_rows = embedded_output._(label="top_rows")
        top_rows.table.wait_for_present()
        assert len(top_rows.table_row.all()) == 5  # head -n 5
        summary = embedded_output._(label="summary")
        summary.table.wait_for_present()
        assert len(summary.table_row.all()) == 8  # head -n 8
        # a static card can't page or sort a table, so it hides those controls, and its compact rows all fit
        top_rows.table_pagination.wait_for_present()
        top_rows.table_pagination.assert_absent_or_hidden()
        top_rows.table_sort_icon.wait_for_present()
        top_rows.table_sort_icon.assert_absent_or_hidden()
        lines = embedded_output._(label="lines")
        lines.collection_element_name.wait_for_present()
        assert [element.text for element in lines.collection_element_name.all()] == ["1", "2"]
        assert "a list with 2" in lines.wait_for_visible().text
        assert embedded_output._(label="numbers_b").text.wait_for_text().strip() == "4"
        plot = embedded_output._(label="plot")
        self._wait_for_image_loaded(plot.image.wait_for_visible())
        self._assert_cards_beside_their_steps()
        # steps only move right, and the inputs and first column of tools stay put
        embedded = self._node_positions()
        for label in OUTPUT_KINDS_LABELS:
            assert embedded[label][0] >= authored[label][0] and embedded[label][1] == authored[label][1], label
        for label in ["table", "image", "text", "head_table", "cat_table", "copy_image", "split_text"]:
            assert embedded[label] == authored[label], label
        # the graph zooms out to fit the cards a moment after they're laid out
        self._wait_on(
            lambda: self._graph_transform() != transform, "graph to refit", wait_type=self.wait_types.UX_RENDER
        )
        assert self._rows_shown(top_rows) == 5
        # the image is sized to the card's body, whatever the picture's own size, and the snapshot doesn't scroll
        fit = self.execute_script(
            "const card = arguments[0].getBoundingClientRect();"
            "const image = arguments[0].querySelector('img').getBoundingClientRect();"
            "const preview = arguments[0].querySelector('.invocation-output-preview');"
            "return {width: image.width / card.width, height: image.height / card.height,"
            " below: image.bottom - card.bottom, scrolls: preview.scrollHeight > preview.clientHeight};",
            plot.wait_for_present(),
        )
        assert fit["width"] > 0.9 and fit["height"] > 0.6 and fit["below"] <= 0 and not fit["scrolls"], fit
        self._assert_embedded_outputs_static()
        self._settle_for_screenshot()
        self.screenshot("invocation_graph_embedded_outputs")

        # up close at 100%: the table, image and collection cards beside their steps
        self._zoom_in_around(
            embedded_output._(label="top_rows"),
            embedded_output._(label="lines"),
            self.components.workflow_editor.node._(label="head_cat"),
        )
        self._settle_for_screenshot()
        self.screenshot("invocation_graph_embedded_outputs_zoomed")

        toggle.wait_for_and_click()
        invocations.graph_embedded_outputs.wait_for_absent()
        assert toggle.wait_for_visible().get_attribute("aria-pressed") == "false"
        assert self._node_positions() == authored

    @selenium_test
    def test_embed_shows_steps_as_their_preferred_output(self):
        self._open_output_kinds_invocation(preferred_outputs=PREFERRED_OUTPUTS)
        invocations = self.components.invocations
        authored = self._node_positions()
        invocations.graph_step_preferred_output._(label="head_table").assert_absent()

        transform = self._graph_transform()
        invocations.graph_embed_outputs_toggle.wait_for_and_click()
        invocations.graph_embedded_outputs.wait_for_present()
        invocations.graph_embedded_outputs_loading.wait_for_absent()
        # the step stands in for its preferred output, so that workflow output gets no card
        labels = [card.get_attribute("data-output-label") for card in invocations.graph_embedded_outputs.all()]
        sources = {label: step for label, step in EMBEDDED_OUTPUT_SOURCES.items() if label != "top_rows"}
        assert sorted(labels) == sorted(sources)

        head_table = invocations.graph_step_preferred_output._(label="head_table")
        head_table.table.wait_for_present()
        assert len(head_table.table_row.all()) == 5  # head -n 5
        # labelled as the workflow output's card would have been
        assert head_table.output_label.wait_for_text().strip() == "top_rows"
        # the step's own output, which the invocation doesn't list, is fetched with the step's details
        cat_table = invocations.graph_step_preferred_output._(label="cat_table")
        cat_table.table.wait_for_present()
        assert cat_table.output_label.wait_for_text().strip() == "out_file1"
        cat_table.table_pagination.wait_for_present()
        cat_table.table_pagination.assert_absent_or_hidden()
        self._assert_static(
            {"head_table": head_table.wait_for_present(), "cat_table": cat_table.wait_for_present()},
            invocations.graph_step_preferred_output_controls.all(),
        )

        self._assert_cards_beside_their_steps(sources)
        embedded = self._node_positions()
        for label in OUTPUT_KINDS_LABELS:
            assert embedded[label][0] >= authored[label][0] and embedded[label][1] == authored[label][1], label
        for label in ["table", "image", "text", "head_table", "copy_image", "split_text"]:
            assert embedded[label] == authored[label], label
        # head_table grew down into cat_table's row, so cat_table moves past it (clear of it, as checked above)
        assert embedded["cat_table"][0] > authored["cat_table"][0]
        self._wait_on(
            lambda: self._graph_transform() != transform, "graph to refit", wait_type=self.wait_types.UX_RENDER
        )
        self._settle_for_screenshot()
        self.screenshot("invocation_graph_embedded_preferred_outputs")

        # up close at 100%: both steps shown as their tables
        node = self.components.workflow_editor.node
        self._zoom_in_around(node._(label="head_table"), node._(label="cat_table"))
        self._settle_for_screenshot()
        self.screenshot("invocation_graph_embedded_preferred_outputs_zoomed")

        invocations.graph_embed_outputs_toggle.wait_for_and_click()
        invocations.graph_embedded_outputs.wait_for_absent()
        head_table.wait_for_absent()
        assert self._node_positions() == authored

    def _graph_transform(self) -> str:
        return str(self.components.invocations.graph_node_area.wait_for_present().value_of_css_property("transform"))

    def _node_positions(self) -> dict[str, tuple[float, float]]:
        """Each step's position on the graph canvas, in workflow coordinates"""
        positions = {}
        for label in OUTPUT_KINDS_LABELS:
            element = self.components.workflow_editor.node._(label=label).wait_for_present()
            left, top = (float(element.value_of_css_property(side).removesuffix("px")) for side in ("left", "top"))
            positions[label] = (left, top)
        return positions

    def _assert_embedded_outputs_static(self) -> None:
        """The cards are snapshots: pointer events go through them to the graph, and nothing in them takes focus"""
        invocations = self.components.invocations
        cards = {card.get_attribute("data-output-label"): card for card in invocations.graph_embedded_outputs.all()}
        self._assert_static(cards, invocations.graph_embedded_output_controls.all())

    def _assert_static(self, snapshots: dict[str, WebElementProtocol], controls: list[WebElementProtocol]) -> None:
        """Pointer events go through these previews, keyed by a label for failures, to what's beneath them, and none
        of their controls takes focus"""
        for label, snapshot in snapshots.items():
            hit = self.execute_script(
                "const r = arguments[0].getBoundingClientRect();"
                "const hit = document.elementFromPoint(r.left + r.width / 2, r.top + r.height / 2);"
                "return hit === null ? null : arguments[0].contains(hit);",
                snapshot,
            )
            assert hit is False, f"{label}'s preview takes the pointer (or is out of view)"
        assert controls, "expected the previews to render controls"
        for control in controls:
            focused = self.execute_script(
                "arguments[0].focus(); return document.activeElement === arguments[0];", control
            )
            assert not focused, f"{control.text!r} in a static preview takes focus"

    @retry_assertion_during_transitions
    def _assert_cards_beside_their_steps(self, sources: dict[str, str] = EMBEDDED_OUTPUT_SOURCES) -> None:
        """Each embedded output sits just right of the step that produced it, level with it, clear of every step,
        and a connector joins the step's right edge to the card. No two steps overlap."""
        invocations = self.components.invocations
        node = self.components.workflow_editor.node
        steps = {label: self._client_rect(node._(label=label).wait_for_present()) for label in OUTPUT_KINDS_LABELS}
        # The layout keeps any overlaps the author made, so this is a property of WORKFLOW_OUTPUT_KINDS, which has
        # none, not of the layout: it checks that steps grown to show their preferred output push their neighbours
        # clear.
        for i, (label, step) in enumerate(steps.items()):
            for other_label, other in list(steps.items())[i + 1 :]:
                assert step.clear_of(other), f"{label} overlaps {other_label}"
        for output_label, step_label in sources.items():
            card = self._client_rect(invocations.graph_embedded_output._(label=output_label).wait_for_present())
            step = steps[step_label]
            just_right = step.right < card.left < step.right + MAX_CARD_GAP
            assert just_right, f"{output_label} is not just right of {step_label}"
            assert abs(card.top - step.top) < EDGE_TOLERANCE, f"{output_label} is not level with {step_label}"
            connector = self._client_rect(
                invocations.graph_embedded_output_connector(label=output_label).wait_for_present()
            )
            joins = (
                abs(connector.left - step.right) < EDGE_TOLERANCE
                and abs(connector.right - card.left) < EDGE_TOLERANCE
                and step.top < connector.top < step.bottom
            )
            assert joins, f"{output_label}'s connector doesn't join {step_label}"
            for other_label, other in steps.items():
                assert card.clear_of(other), f"{output_label} overlaps {other_label}"

    def _rows_shown(self, preview: SmartComponent) -> int:
        """How many of the preview's table rows it shows in full, rather than clipping (measured at once)"""
        return self.execute_script(
            "const bottom = arguments[0].getBoundingClientRect().bottom;"
            "return [...arguments[0].querySelectorAll('table.g-table tbody tr')]"
            ".filter((row) => row.getBoundingClientRect().bottom <= bottom + arguments[1]).length;",
            preview.wait_for_present(),
            EDGE_TOLERANCE,
        )

    def _client_rect(self, element: WebElementProtocol) -> ClientRect:
        """The element's on-screen bounding box"""
        return ClientRect(
            *self.execute_script(
                "const r = arguments[0].getBoundingClientRect(); return [r.left, r.top, r.right, r.bottom];", element
            )
        )

    def _open_output_kinds_invocation(self, preferred_outputs: dict[str, str] | None = None) -> None:
        if preferred_outputs:
            # format 2 workflows can't name a preferred output yet, so set it on the converted native workflow
            as_python = ordered_load(WORKFLOW_OUTPUT_KINDS)
            native = python_to_workflow(as_python, galaxy_interface=None, workflow_directory=None)
            for step in native["steps"].values():
                if step.get("label") in preferred_outputs:
                    step["preferred_output"] = preferred_outputs[step["label"]]
            self._open_invocation(native, OUTPUT_KINDS_LABELS, test_data=as_python["test_data"], client_convert=False)
        else:
            self._open_invocation(WORKFLOW_OUTPUT_KINDS, OUTPUT_KINDS_LABELS)
        # the pointer is still on the activity that closed the invocations panel; move it off that tooltip
        self.clear_tooltips()
        self.components.invocations.activity_tooltip.wait_for_absent_or_hidden()
        # and drop the focus that click left there, so screenshots and Escape presses don't draw a focus ring on it
        self._drop_focus()

    def _drop_focus(self) -> None:
        self.execute_script("document.activeElement.blur();")

    def _settle_for_screenshot(self) -> None:
        """Keep tooltips and focus rings out of the next screenshot, waiting out the transitions that fade them"""
        self.clear_tooltips()
        self._drop_focus()
        self._wait_on(
            lambda: self.execute_script(
                "return document.getAnimations().every((animation) => !(animation instanceof CSSTransition));"
            ),
            "transitions to finish",
            wait_type=self.wait_types.UX_TRANSITION,
        )

    def _zoom_in_around(self, *targets: SmartComponent) -> None:
        """Pan the graph to center these targets, then reset the zoom to 100%, which scales about the center"""
        boxes = [self._client_rect(target.wait_for_present()) for target in targets]
        canvas_body = self.components.workflow_editor.canvas_body.wait_for_visible()
        canvas = self._client_rect(canvas_body)
        left, right = min(box.left for box in boxes), max(box.right for box in boxes)
        top, bottom = min(box.top for box in boxes), max(box.bottom for box in boxes)
        offset = (
            round((canvas.left + canvas.right - left - right) / 2),
            round((canvas.top + canvas.bottom - top - bottom) / 2),
        )
        # the drag starts mid-canvas, on background in this layout, so it pans the graph instead of grabbing a step
        self.mouse_drag(from_element=canvas_body, to_offset=offset)
        transform = self._graph_transform()
        self.components.invocations.graph_zoom_reset.wait_for_and_click()
        self._wait_on(
            lambda: self._graph_transform() != transform, "graph to zoom", wait_type=self.wait_types.UX_RENDER
        )

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

    def _open_invocation(self, workflow: str | dict[str, Any], labels: list[str], **run_kwds: Any):
        """Run the workflow (``run_kwds`` go to ``run_workflow``), open its invocation and wait for these steps"""
        self.workflow_populator.run_workflow(workflow, history_id=self.current_history_id(), **run_kwds)
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
