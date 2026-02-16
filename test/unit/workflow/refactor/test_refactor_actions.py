"""Unit tests for workflow refactor schema and executor additions (Step 2).

Tests cover:
- UpdateStepPositionAction: position_absolute vs position_shift, validation
- RemoveStepAction: connection cleanup, workflow output messages, sparse dict handling
- Comment actions: add, delete, update position/size/color/data, remove all freehand
- Schema validation: model_validator on UpdateStepPositionAction
"""

from typing import Any
from unittest.mock import MagicMock

import pytest
from pydantic import ValidationError

from galaxy.workflow.refactor.execute import WorkflowRefactorExecutor
from galaxy.workflow.refactor.schema import (
    AddCommentAction,
    AddStepAction,
    DeleteCommentAction,
    RefactorActionExecution,
    RefactorActionExecutionMessageTypeEnum,
    RefactorActions,
    RemoveAllFreehandCommentsAction,
    RemoveStepAction,
    UpdateCommentColorAction,
    UpdateCommentDataAction,
    UpdateCommentPositionAction,
    UpdateCommentSizeAction,
    UpdateStepPositionAction,
)

# --- Fixtures ---


def _make_raw_workflow_description(as_dict):
    """Minimal RawWorkflowDescription mock."""
    desc = MagicMock()
    desc.as_dict = as_dict
    return desc


def _make_executor(as_dict):
    """Create executor with mocked workflow/injector — only _as_dict-based methods work."""
    raw = _make_raw_workflow_description(as_dict)
    workflow = MagicMock()
    workflow.steps = {}
    injector = MagicMock()
    injector.allow_tool_state_corrections = False
    return WorkflowRefactorExecutor(raw, workflow, injector)


def _run_action(executor, action):
    """Run a single action and return the execution result."""
    execution = RefactorActionExecution(action=action, messages=[])
    method = getattr(executor, f"_apply_{action.action_type}")
    method(action, execution)
    return execution


def _simple_two_step_workflow():
    """Workflow with two steps connected: step 0 (input) -> step 1 (tool)."""
    return {
        "steps": {
            0: {
                "id": 0,
                "order_index": 0,
                "type": "data_input",
                "label": "input1",
                "position": {"left": 100, "top": 200},
                "input_connections": {},
                "workflow_outputs": [],
            },
            1: {
                "id": 1,
                "order_index": 1,
                "type": "tool",
                "label": "tool1",
                "position": {"left": 300, "top": 200},
                "input_connections": {
                    "input1": [{"id": 0, "output_name": "output"}],
                },
                "workflow_outputs": [
                    {"output_name": "out_file1", "label": "wf_output"},
                ],
            },
        },
    }


def _three_step_chain():
    """step0 -> step1 -> step2, all connected."""
    return {
        "steps": {
            0: {
                "id": 0,
                "order_index": 0,
                "type": "data_input",
                "label": "input1",
                "position": {"left": 0, "top": 0},
                "input_connections": {},
                "workflow_outputs": [],
            },
            1: {
                "id": 1,
                "order_index": 1,
                "type": "tool",
                "label": "middle",
                "position": {"left": 200, "top": 0},
                "input_connections": {
                    "input1": [{"id": 0, "output_name": "output"}],
                },
                "workflow_outputs": [
                    {"output_name": "out1", "label": "middle_output"},
                ],
            },
            2: {
                "id": 2,
                "order_index": 2,
                "type": "tool",
                "label": "final",
                "position": {"left": 400, "top": 0},
                "input_connections": {
                    "input1": [{"id": 1, "output_name": "out1"}],
                },
                "workflow_outputs": [],
            },
        },
    }


def _workflow_with_comments():
    return {
        "steps": {},
        "comments": [
            {
                "id": 0,
                "type": "text",
                "position": [10, 20],
                "size": [100, 50],
                "color": "none",
                "data": {"text": "hello"},
            },
            {
                "id": 1,
                "type": "freehand",
                "position": [30, 40],
                "size": [200, 100],
                "color": "blue",
                "data": {"line": [[0, 0], [10, 10]]},
            },
            {
                "id": 2,
                "type": "markdown",
                "position": [50, 60],
                "size": [150, 75],
                "color": "none",
                "data": {"text": "# Title"},
            },
        ],
    }


# --- Schema validation tests ---


class TestUpdateStepPositionSchema:
    def test_position_absolute_only(self):
        action = UpdateStepPositionAction(
            action_type="update_step_position",
            step={"order_index": 0},
            position_absolute={"left": 100, "top": 200},
        )
        assert action.position_absolute is not None
        assert action.position_shift is None

    def test_position_shift_only(self):
        action = UpdateStepPositionAction(
            action_type="update_step_position",
            step={"order_index": 0},
            position_shift={"left": 10, "top": -5},
        )
        assert action.position_shift is not None
        assert action.position_absolute is None

    def test_neither_position_raises(self):
        with pytest.raises(ValidationError, match="Must provide either"):
            UpdateStepPositionAction(
                action_type="update_step_position",
                step={"order_index": 0},
            )

    def test_both_positions_raises(self):
        with pytest.raises(ValidationError, match="Cannot provide both"):
            UpdateStepPositionAction(
                action_type="update_step_position",
                step={"order_index": 0},
                position_shift={"left": 1, "top": 1},
                position_absolute={"left": 100, "top": 200},
            )


class TestActionDiscriminator:
    def test_all_new_action_types_registered(self):
        """Verify new action types are discoverable via RefactorActions."""
        new_types = [
            "remove_step",
            "add_comment",
            "delete_comment",
            "update_comment_position",
            "update_comment_size",
            "update_comment_color",
            "update_comment_data",
            "remove_all_freehand_comments",
        ]
        for action_type in new_types:
            from galaxy.workflow.refactor.schema import ACTION_CLASSES_BY_TYPE

            assert action_type in ACTION_CLASSES_BY_TYPE, f"{action_type} not registered"

    def test_refactor_actions_parses_remove_step(self):
        req = RefactorActions(actions=[{"action_type": "remove_step", "step": {"order_index": 0}}])
        assert isinstance(req.actions[0], RemoveStepAction)

    def test_refactor_actions_parses_add_comment(self):
        req = RefactorActions(
            actions=[
                {
                    "action_type": "add_comment",
                    "type": "text",
                    "position": {"left": 0, "top": 0},
                    "size": {"width": 100, "height": 50},
                    "color": "none",
                    "data": {"text": "hi"},
                }
            ]
        )
        assert isinstance(req.actions[0], AddCommentAction)


# --- UpdateStepPosition executor tests ---


class TestUpdateStepPosition:
    def test_position_absolute_sets_position(self):
        wf = _simple_two_step_workflow()
        executor = _make_executor(wf)
        action = UpdateStepPositionAction(
            action_type="update_step_position",
            step={"order_index": 0},
            position_absolute={"left": 500, "top": 600},
        )
        _run_action(executor, action)
        assert wf["steps"][0]["position"] == {"left": 500, "top": 600}

    def test_position_shift_adds_delta(self):
        wf = _simple_two_step_workflow()
        executor = _make_executor(wf)
        action = UpdateStepPositionAction(
            action_type="update_step_position",
            step={"order_index": 0},
            position_shift={"left": 50, "top": -30},
        )
        _run_action(executor, action)
        assert wf["steps"][0]["position"] == {"left": 150, "top": 170}

    def test_position_shift_with_missing_defaults(self):
        wf = _simple_two_step_workflow()
        del wf["steps"][0]["position"]["left"]
        executor = _make_executor(wf)
        action = UpdateStepPositionAction(
            action_type="update_step_position",
            step={"order_index": 0},
            position_shift={"left": 10, "top": 5},
        )
        _run_action(executor, action)
        assert wf["steps"][0]["position"]["left"] == 10
        assert wf["steps"][0]["position"]["top"] == 205

    def test_position_absolute_by_label(self):
        wf = _simple_two_step_workflow()
        executor = _make_executor(wf)
        action = UpdateStepPositionAction(
            action_type="update_step_position",
            step={"label": "tool1"},
            position_absolute={"left": 999, "top": 888},
        )
        _run_action(executor, action)
        assert wf["steps"][1]["position"] == {"left": 999, "top": 888}


# --- RemoveStep executor tests ---


class TestRemoveStep:
    def test_remove_isolated_step(self):
        wf = _simple_two_step_workflow()
        # Remove input step — tool1 should lose its inbound connection
        executor = _make_executor(wf)
        action = RemoveStepAction(action_type="remove_step", step={"order_index": 0})
        execution = _run_action(executor, action)
        assert 0 not in wf["steps"]
        assert 1 in wf["steps"]
        # Should have connection_drop messages
        conn_msgs = [
            m
            for m in execution.messages
            if m.message_type == RefactorActionExecutionMessageTypeEnum.connection_drop_forced
        ]
        assert len(conn_msgs) >= 1

    def test_remove_step_cleans_outbound_connections(self):
        wf = _three_step_chain()
        executor = _make_executor(wf)
        # Remove middle step (step 1) — step 2's inbound connection should be cleaned
        action = RemoveStepAction(action_type="remove_step", step={"order_index": 1})
        _run_action(executor, action)
        assert 1 not in wf["steps"]
        # step 2's input_connections should have had the connection to step 1 removed
        remaining_conns = wf["steps"][2]["input_connections"]["input1"]
        assert all(c["id"] != 1 for c in remaining_conns)

    def test_remove_step_emits_workflow_output_message(self):
        wf = _three_step_chain()
        executor = _make_executor(wf)
        action = RemoveStepAction(action_type="remove_step", step={"order_index": 1})
        execution = _run_action(executor, action)
        wo_msgs = [
            m
            for m in execution.messages
            if m.message_type == RefactorActionExecutionMessageTypeEnum.workflow_output_drop_forced
        ]
        assert len(wo_msgs) == 1
        assert wo_msgs[0].output_label == "middle_output"

    def test_remove_step_cleans_inbound_connections(self):
        wf = _three_step_chain()
        executor = _make_executor(wf)
        # Remove middle step — messages should include the inbound connection from step 0
        action = RemoveStepAction(action_type="remove_step", step={"order_index": 1})
        execution = _run_action(executor, action)
        conn_msgs = [
            m
            for m in execution.messages
            if m.message_type == RefactorActionExecutionMessageTypeEnum.connection_drop_forced
        ]
        # Should have messages for both inbound (from step 0) and outbound (to step 2) connections
        assert len(conn_msgs) >= 2

    def test_remove_step_by_label(self):
        wf = _simple_two_step_workflow()
        executor = _make_executor(wf)
        action = RemoveStepAction(action_type="remove_step", step={"label": "input1"})
        _run_action(executor, action)
        assert 0 not in wf["steps"]

    def test_remove_step_sparse_dict_tolerance(self):
        """After removing step 0, step 1 should still be accessible."""
        wf = _simple_two_step_workflow()
        executor = _make_executor(wf)
        action0 = RemoveStepAction(action_type="remove_step", step={"order_index": 0})
        _run_action(executor, action0)
        assert 0 not in wf["steps"]
        # step 1 should still resolve by order_index
        action1 = UpdateStepPositionAction(
            action_type="update_step_position",
            step={"order_index": 1},
            position_absolute={"left": 0, "top": 0},
        )
        _run_action(executor, action1)
        assert wf["steps"][1]["position"] == {"left": 0, "top": 0}

    def test_remove_then_add_no_collision(self):
        """add_step after remove_step must not collide with remaining steps."""
        wf = _three_step_chain()
        executor = _make_executor(wf)
        # Remove middle step -> dict becomes {0, 2}, sparse
        _run_action(executor, RemoveStepAction(action_type="remove_step", step={"order_index": 1}))
        assert 1 not in wf["steps"]
        assert 2 in wf["steps"]
        # Add a new step — should get order_index 3, not 2
        _run_action(executor, AddStepAction(action_type="add_step", type="tool", label="new_step"))
        assert 3 in wf["steps"], f"Expected new step at index 3, got keys: {list(wf['steps'].keys())}"
        # Original step 2 must be untouched
        assert wf["steps"][2]["label"] == "final"
        assert wf["steps"][3]["label"] == "new_step"

    def test_remove_step_no_connections(self):
        """Remove a step with no connections — should produce no connection messages."""
        wf = {
            "steps": {
                0: {
                    "id": 0,
                    "order_index": 0,
                    "type": "data_input",
                    "label": "lone",
                    "position": {"left": 0, "top": 0},
                    "input_connections": {},
                    "workflow_outputs": [],
                },
            },
        }
        executor = _make_executor(wf)
        action = RemoveStepAction(action_type="remove_step", step={"order_index": 0})
        execution = _run_action(executor, action)
        assert 0 not in wf["steps"]
        assert len(execution.messages) == 0


# --- Comment action executor tests ---


class TestAddComment:
    def test_add_comment_to_empty(self):
        wf: dict[str, Any] = {"steps": {}}
        executor = _make_executor(wf)
        action = AddCommentAction(
            action_type="add_comment",
            type="text",
            position={"left": 10, "top": 20},
            size={"width": 100, "height": 50},
            color="none",
            data={"text": "hello"},
        )
        _run_action(executor, action)
        assert len(wf["comments"]) == 1
        c = wf["comments"][0]
        assert c["id"] == 0
        assert c["type"] == "text"
        assert c["position"] == [10, 20]
        assert c["size"] == [100, 50]
        assert c["color"] == "none"
        assert c["data"] == {"text": "hello"}

    def test_add_comment_increments_id(self):
        wf = _workflow_with_comments()
        executor = _make_executor(wf)
        action = AddCommentAction(
            action_type="add_comment",
            type="frame",
            position={"left": 0, "top": 0},
            size={"width": 500, "height": 500},
            color="red",
            data={"title": "My Frame"},
        )
        _run_action(executor, action)
        assert len(wf["comments"]) == 4
        assert wf["comments"][-1]["id"] == 3


class TestDeleteComment:
    def test_delete_comment(self):
        wf = _workflow_with_comments()
        executor = _make_executor(wf)
        action = DeleteCommentAction(
            action_type="delete_comment",
            comment={"comment_id": 1},
        )
        _run_action(executor, action)
        assert len(wf["comments"]) == 2
        ids = [c["id"] for c in wf["comments"]]
        assert 1 not in ids

    def test_delete_comment_not_found(self):
        wf = _workflow_with_comments()
        executor = _make_executor(wf)
        action = DeleteCommentAction(
            action_type="delete_comment",
            comment={"comment_id": 999},
        )
        with pytest.raises(Exception, match="Failed to find comment"):
            _run_action(executor, action)


class TestUpdateCommentPosition:
    def test_update_position(self):
        wf = _workflow_with_comments()
        executor = _make_executor(wf)
        action = UpdateCommentPositionAction(
            action_type="update_comment_position",
            comment={"comment_id": 0},
            position={"left": 99, "top": 88},
        )
        _run_action(executor, action)
        assert wf["comments"][0]["position"] == [99, 88]


class TestUpdateCommentSize:
    def test_update_size(self):
        wf = _workflow_with_comments()
        executor = _make_executor(wf)
        action = UpdateCommentSizeAction(
            action_type="update_comment_size",
            comment={"comment_id": 0},
            size={"width": 300, "height": 200},
        )
        _run_action(executor, action)
        assert wf["comments"][0]["size"] == [300, 200]


class TestUpdateCommentColor:
    def test_update_color(self):
        wf = _workflow_with_comments()
        executor = _make_executor(wf)
        action = UpdateCommentColorAction(
            action_type="update_comment_color",
            comment={"comment_id": 2},
            color="green",
        )
        _run_action(executor, action)
        assert wf["comments"][2]["color"] == "green"


class TestUpdateCommentData:
    def test_update_data(self):
        wf = _workflow_with_comments()
        executor = _make_executor(wf)
        action = UpdateCommentDataAction(
            action_type="update_comment_data",
            comment={"comment_id": 0},
            data={"text": "updated text"},
        )
        _run_action(executor, action)
        assert wf["comments"][0]["data"] == {"text": "updated text"}


class TestRemoveAllFreehandComments:
    def test_removes_only_freehand(self):
        wf = _workflow_with_comments()
        executor = _make_executor(wf)
        action = RemoveAllFreehandCommentsAction(
            action_type="remove_all_freehand_comments",
        )
        _run_action(executor, action)
        assert len(wf["comments"]) == 2
        types = [c["type"] for c in wf["comments"]]
        assert "freehand" not in types

    def test_no_freehand_is_noop(self):
        wf = {
            "steps": {},
            "comments": [{"id": 0, "type": "text", "position": [0, 0], "size": [10, 10], "color": "none", "data": {}}],
        }
        executor = _make_executor(wf)
        action = RemoveAllFreehandCommentsAction(action_type="remove_all_freehand_comments")
        _run_action(executor, action)
        assert len(wf["comments"]) == 1

    def test_empty_comments(self):
        wf: dict[str, Any] = {"steps": {}}
        executor = _make_executor(wf)
        action = RemoveAllFreehandCommentsAction(action_type="remove_all_freehand_comments")
        _run_action(executor, action)
        assert wf.get("comments", []) == []
