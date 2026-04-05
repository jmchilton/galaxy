"""Encoding validators for --strict-encoding.

Checks that workflow dicts use proper Python types (dicts, lists) for
tool_state / state fields rather than JSON-string-where-dict-expected.

Only outer-level checks are performed — modern (nested=True) encoding always
produces proper dicts/lists after one decode, and the walker no longer
silently decodes JSON-string containers (commit 67aa42d). Legacy-encoded
workflows are caught by precheck.py / --strict-state.
"""

from typing import (
    Any,
    Dict,
    List,
)

__all__ = (
    "validate_encoding_native",
    "validate_encoding_format2",
)


def validate_encoding_native(workflow_dict: Dict[str, Any]) -> List[str]:
    """Check that a native workflow's tool_state values are proper dicts.

    Returns a list of error messages. Empty list means clean encoding.
    """
    errors: List[str] = []
    steps = workflow_dict.get("steps") or {}
    if not isinstance(steps, dict):
        return errors
    for step_id, step in steps.items():
        if not isinstance(step, dict):
            continue
        step_type = step.get("type")
        if step_type and step_type != "tool":
            continue
        if "tool_state" not in step:
            continue
        tool_state = step.get("tool_state")
        if tool_state is None:
            continue
        if isinstance(tool_state, str):
            errors.append(f"Step {step_id}: tool_state is a JSON string, expected dict")
    return errors


def validate_encoding_format2(workflow_dict: Dict[str, Any]) -> List[str]:
    """Check that a format2 workflow uses `state` (not `tool_state`) and values are proper dicts."""
    errors: List[str] = []
    steps = workflow_dict.get("steps")
    if isinstance(steps, list):
        items = list(enumerate(steps))
    elif isinstance(steps, dict):
        items = list(steps.items())
    else:
        return errors
    for key, step in items:
        if not isinstance(step, dict):
            continue
        has_tool_state = step.get("tool_state") is not None
        has_state = step.get("state") is not None
        if has_tool_state and not has_state:
            errors.append(f"Step {key}: uses `tool_state` instead of `state` (format2)")
        state = step.get("state") if has_state else step.get("tool_state")
        if isinstance(state, str):
            errors.append(f"Step {key}: state is a JSON string, expected dict")
    return errors
