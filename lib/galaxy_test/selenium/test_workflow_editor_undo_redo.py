from .framework import (
    RunsWorkflows,
    selenium_test,
    SeleniumTestCase,
    UsesWorkflowAssertions,
)

WORKFLOW_CONNECTED_CAT = """
class: GalaxyWorkflow
inputs:
  the_input: data
steps:
  the_cat:
    tool_id: cat
    in:
      input1: the_input
"""


class TestWorkflowEditorUndoRedo(SeleniumTestCase, RunsWorkflows, UsesWorkflowAssertions):
    ensure_registered = True

    @selenium_test
    def test_editor_change_stack_inserting_inputs(self):
        editor = self.components.workflow_editor
        annotation = "change_stack_test_inserting_inputs"
        self.workflow_create_new(annotation=annotation)

        self.workflow_editor_add_input(item_name="data_input")
        self.workflow_editor_add_input(item_name="data_collection_input")
        self.workflow_editor_add_input(item_name="parameter_input")

        editor.node.by_id(id=0).wait_for_present()
        editor.node.by_id(id=1).wait_for_present()
        editor.node.by_id(id=2).wait_for_present()

        editor.tool_bar.changes.wait_for_and_click()
        changes = editor.changes

        changes.action_insert_data_input.wait_for_present()
        changes.action_insert_data_collection_input.wait_for_present()
        changes.action_insert_parameter.wait_for_present()

        # Undo all of it by clicking the first node.
        changes.action_insert_data_input.wait_for_and_click()
        editor.node.by_id(id=0).assert_absent_or_hidden_after_transitions()
        editor.node.by_id(id=1).assert_absent_or_hidden_after_transitions()
        editor.node.by_id(id=2).assert_absent_or_hidden_after_transitions()

        # now that same action has become a redo, so we should have a node back afterward.
        changes.action_insert_data_input.wait_for_and_click()
        editor.node.by_id(id=0).wait_for_present()
        editor.node.by_id(id=1).assert_absent_or_hidden_after_transitions()
        editor.node.by_id(id=2).assert_absent_or_hidden_after_transitions()

        changes.action_insert_data_collection_input.wait_for_and_click()
        editor.node.by_id(id=0).wait_for_present()
        editor.node.by_id(id=1).wait_for_present()
        editor.node.by_id(id=2).assert_absent_or_hidden_after_transitions()

        changes.action_insert_parameter.wait_for_and_click()
        editor.node.by_id(id=0).wait_for_present()
        editor.node.by_id(id=1).wait_for_present()
        editor.node.by_id(id=2).wait_for_present()

    @selenium_test
    def test_editor_change_stack_set_attributes(self):
        editor = self.components.workflow_editor
        annotation = "change_stack_test_set_attributes"
        name = self.workflow_create_new(annotation=annotation)

        assert "Do not specify" in self.workflow_editor_license_text()
        self.workflow_editor_set_license("MIT")
        assert "MIT" in self.workflow_editor_license_text()

        editor.tool_bar.changes.wait_for_and_click()

        changes = editor.changes
        changes.action_set_license.wait_for_and_click()
        # it switches back so this isn't needed per se
        # editor.tool_bar.attributes.wait_for_and_click()
        assert "Do not specify" in self.workflow_editor_license_text()

        # for annotation we want to reset the change stack to dismiss
        # the original setting of the annotation
        name = self.workflow_index_open_with_name(name)

        annotation_modified = "change_stack_test_set_attributes modified!!!"

        self.workflow_editor_set_annotation(annotation_modified)
        self.assert_wf_annotation_is(annotation_modified)

        editor.tool_bar.changes.wait_for_and_click()
        changes.action_set_annotation.wait_for_and_click()

        self.assert_wf_annotation_is(annotation)

    @selenium_test
    def test_undo_redo_step_lifecycle(self):
        editor = self.components.workflow_editor
        self.workflow_create_new(annotation="undo_redo_step_lifecycle")

        # Add a data input step
        self.workflow_editor_add_input(item_name="data_input")
        editor.node.by_id(id=0).wait_for_present()

        # Set label — need to wait for lazy action to commit (2s timeout)
        self.workflow_editor_set_node_label("MyTool", node=0)
        editor.canvas_body.wait_for_and_click()
        self.sleep_for(self.wait_types.UX_TRANSITION)
        editor.node._(label="MyTool").wait_for_present()

        # Undo label
        self.workflow_editor_undo()
        editor.node._(label="MyTool").assert_absent_or_hidden_after_transitions()
        editor.node.by_id(id=0).wait_for_present()

        # Redo label — redo opens tool inspector, close it before clicking node
        self.workflow_editor_redo()
        editor.node._(label="MyTool").wait_for_present()
        editor.node_inspector_close.wait_for_and_click()

        # Duplicate node
        self.workflow_editor_duplicate_node(label="MyTool")
        editor.node.by_id(id=1).wait_for_present()

        # Undo duplicate
        self.workflow_editor_undo()
        editor.node.by_id(id=1).assert_absent_or_hidden_after_transitions()
        editor.node.by_id(id=0).wait_for_present()

        # Redo duplicate
        self.workflow_editor_redo()
        editor.node.by_id(id=1).wait_for_present()

        # Destroy original node
        self.workflow_editor_destroy_node(label="MyTool")
        editor.node.by_id(id=0).assert_absent_or_hidden_after_transitions()
        editor.node.by_id(id=1).wait_for_present()

        # Undo destroy
        self.workflow_editor_undo()
        editor.node.by_id(id=0).wait_for_present()

        # Verify changes panel shows all action types
        self.workflow_editor_open_changes_panel()
        changes = editor.changes
        changes.action_set_label.wait_for_present()
        changes.action_step_copy.wait_for_present()
        changes.action_step_remove.wait_for_present()

    @selenium_test
    def test_undo_redo_workflow_metadata(self):
        editor = self.components.workflow_editor
        name = self.workflow_create_new(annotation="orig_ann", clear_placeholder=True)

        # Set name — lazy action, blur + wait for commit
        self.workflow_editor_set_name("NewName")
        editor.canvas_body.wait_for_and_click()
        self.sleep_for(self.wait_types.UX_TRANSITION)
        self.assert_wf_name_is("NewName")

        # Undo name → reverts to original random name
        self.workflow_editor_undo()
        self.assert_wf_name_is(name)

        # Redo name
        self.workflow_editor_redo()
        self.assert_wf_name_is("NewName")

        # Set license
        self.workflow_editor_set_license("MIT")
        assert "MIT" in self.workflow_editor_license_text()

        # Undo license
        self.workflow_editor_undo()
        assert "Do not specify" in self.workflow_editor_license_text()

        # Redo license
        self.workflow_editor_redo()
        assert "MIT" in self.workflow_editor_license_text()

        # Set annotation — lazy action, blur + wait for commit
        self.workflow_editor_set_annotation("new_ann")
        editor.canvas_body.wait_for_and_click()
        self.sleep_for(self.wait_types.UX_TRANSITION)
        self.assert_wf_annotation_is("new_ann")

        # Undo annotation → reverts to "orig_ann"
        self.workflow_editor_undo()
        self.assert_wf_annotation_is("orig_ann")

        # Verify changes panel entries
        self.workflow_editor_open_changes_panel()
        changes = editor.changes
        changes.action_set_name.wait_for_present()
        changes.action_set_license.wait_for_present()
        changes.action_set_annotation.wait_for_present()

    @selenium_test
    def test_undo_redo_connections(self):
        editor = self.components.workflow_editor

        # Load pre-connected workflow and apply auto-layout
        name = self.workflow_upload_yaml_with_random_name(WORKFLOW_CONNECTED_CAT)
        self.workflow_index_open()
        self.workflow_index_open_with_name(name)
        editor.tool_bar.auto_layout.wait_for_and_click()
        self.sleep_for(self.wait_types.UX_RENDER)

        source_sink = ("the_input#output", "the_cat#input1")

        # Verify initial connection
        self.assert_connected(*source_sink)

        # Disconnect
        self.workflow_editor_destroy_connection("the_cat#input1")
        self.assert_not_connected(*source_sink)

        # Undo disconnect → connection restored
        self.workflow_editor_undo()
        self.assert_connected(*source_sink)

        # Redo disconnect → disconnected again
        self.workflow_editor_redo()
        self.assert_not_connected(*source_sink)

        # Remove source step (while disconnected)
        self.workflow_editor_destroy_node(label="the_input")
        editor.node._(label="the_input").assert_absent_or_hidden_after_transitions()

        # Changes panel — both disconnect and step-remove visible
        self.workflow_editor_open_changes_panel()
        changes = editor.changes
        changes.action_disconnect.wait_for_present()
        changes.action_step_remove.wait_for_present()

        # Undo step removal → step restored (still disconnected)
        self.workflow_editor_undo()
        editor.node._(label="the_input").wait_for_present()
        self.assert_not_connected(*source_sink)

        # Undo disconnect → connection restored
        self.workflow_editor_undo()
        self.assert_connected(*source_sink)

    @selenium_test
    def test_undo_redo_comments(self):
        editor = self.components.workflow_editor
        self.workflow_create_new(annotation="undo_redo_comments")

        # Place text comment (upper-left area)
        self.workflow_editor_place_comment("text_comment", offset_x=-200, offset_y=-150)
        # HACK: extra sleep for slow CI — place_comment's internal UX_RENDER not enough.
        # TODO: remove before merge, fix underlying race in place_comment or comment rendering.
        self.sleep_for(self.wait_types.UX_TRANSITION)
        editor.comment.text_comment.wait_for_present()

        # Undo add → text comment gone
        self.workflow_editor_undo()
        editor.comment.text_comment.assert_absent_or_hidden_after_transitions()

        # Redo add → text comment back
        self.workflow_editor_redo()
        editor.comment.text_comment.wait_for_present()

        # Place frame comment (lower-right area, away from text comment)
        self.workflow_editor_place_comment("frame_comment", offset_x=200, offset_y=150)
        editor.comment.frame_comment.wait_for_present()

        # Change text comment color to pink
        self.workflow_editor_change_comment_color("pink", comment_type="text")

        # Undo color change
        self.workflow_editor_undo()

        # Redo color change
        self.workflow_editor_redo()

        # Delete frame comment (keeps all 4 action types in undo stack)
        self.workflow_editor_delete_comment("frame")
        editor.comment.frame_comment.assert_absent_or_hidden_after_transitions()

        # Undo delete → frame comment restored
        self.workflow_editor_undo()
        editor.comment.frame_comment.wait_for_present()

        # Redo delete for final state
        self.workflow_editor_redo()
        editor.comment.frame_comment.assert_absent_or_hidden_after_transitions()

        # Verify changes panel shows all comment action types
        self.workflow_editor_open_changes_panel()
        changes = editor.changes
        changes.action_comment_add.wait_for_present()
        changes.action_comment_color.wait_for_present()
        changes.action_comment_delete.wait_for_present()

    @selenium_test
    def test_undo_redo_multi_action_sequences(self):
        editor = self.components.workflow_editor
        self.workflow_create_new(annotation="multi_action_sequences")

        # Action 1: add data input
        self.workflow_editor_add_input(item_name="data_input")
        editor.node.by_id(id=0).wait_for_present()

        # Action 2: set label "A" (lazy action — blur + wait)
        self.workflow_editor_set_node_label("A", node=0)
        editor.canvas_body.wait_for_and_click()
        self.sleep_for(self.wait_types.UX_TRANSITION)
        editor.node._(label="A").wait_for_present()

        # Action 3: add another input
        self.workflow_editor_add_input(item_name="data_collection_input")
        editor.node.by_id(id=1).wait_for_present()

        # Undo action 3 → second input gone, first still labelled "A"
        self.workflow_editor_undo()
        editor.node.by_id(id=1).assert_absent_or_hidden_after_transitions()
        editor.node._(label="A").wait_for_present()

        # Undo action 2 → label reverted
        self.workflow_editor_undo()
        editor.node._(label="A").assert_absent_or_hidden_after_transitions()
        editor.node.by_id(id=0).wait_for_present()

        # Undo action 1 → first input gone
        self.workflow_editor_undo()
        editor.node.by_id(id=0).assert_absent_or_hidden_after_transitions()

        # Redo all 3
        self.workflow_editor_redo()
        self.workflow_editor_redo()
        self.workflow_editor_redo()
        editor.node._(label="A").wait_for_present()
        editor.node.by_id(id=1).wait_for_present()

        # Undo last 2, then add new step → redo stack should be cleared
        self.workflow_editor_undo()
        self.workflow_editor_undo()
        editor.node.by_id(id=0).wait_for_present()
        editor.node._(label="A").assert_absent_or_hidden_after_transitions()
        editor.node.by_id(id=1).assert_absent_or_hidden_after_transitions()

        # New action (action 4) replaces redo stack
        self.workflow_editor_add_input(item_name="parameter_input")
        editor.node.by_id(id=1).wait_for_present()

        # Redo → no-op (redo stack cleared by action 4)
        self.workflow_editor_redo()
        # Still just 2 nodes (ids 0 and 1)
        editor.node.by_id(id=0).wait_for_present()
        editor.node.by_id(id=1).wait_for_present()

        # Changes panel multi-undo: click first action to undo all
        self.workflow_editor_open_changes_panel()
        changes = editor.changes
        changes.action_insert_data_input.wait_for_and_click()
        editor.node.by_id(id=0).assert_absent_or_hidden_after_transitions()
        editor.node.by_id(id=1).assert_absent_or_hidden_after_transitions()

        # Changes panel multi-redo: click last redo item to redo all
        changes.action_insert_parameter.wait_for_and_click()
        editor.node.by_id(id=0).wait_for_present()
        editor.node.by_id(id=1).wait_for_present()
