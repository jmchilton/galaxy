"""Shared tree walker for native Galaxy workflow tool state.

Handles the recursive traversal of native tool state dicts, including:
- Conditional branch selection (with __current_case__ fallback)
- Repeat instance expansion from input_connections
- Section/container JSON string decoding
- Unknown key checking for validation

Used by both convert.py (building format2 state) and
validation_native.py (merge + validate in one pass).
"""

import json
from typing import (
    Any,
    cast,
    List,
    Optional,
)

from galaxy.tool_util.parameters import (
    ConditionalParameterModel,
    ConditionalWhen,
    flat_state_path,
    repeat_inputs_to_array,
    RepeatParameterModel,
    ToolParameterT,
    validate_explicit_conditional_test_value,
)
from galaxy.tool_util_models.parameters import SectionParameterModel
from ._types import NativeStepDict


class _SkipValue:
    """Sentinel returned by leaf callbacks to omit a value from the walker's output dict."""
    pass


SKIP_VALUE = _SkipValue()

_NATIVE_BOOKKEEPING_KEYS = frozenset({
    "__current_case__",
    "__index__",
    "__page__",
    "__rerun_remap_job_id__",
    "__job_resource",
    "chromInfo",
})


def walk_native_state(
    step: NativeStepDict,
    tool_inputs: List[ToolParameterT],
    state: dict,
    leaf_callback,  # (tool_input: ToolParameterT, value: Any, state_path: str) -> Any | _SkipValue
    prefix: Optional[str] = None,
    check_unknown_keys: bool = False,
) -> dict:
    """Walk native tool state tree, calling leaf_callback for each leaf parameter.

    Handles: conditional branch selection (with __current_case__ fallback),
    repeat instance expansion from input_connections, section/container JSON decode.

    Returns dict of {param_name: callback_result} for non-skipped leaves,
    with nested dicts for conditionals/sections and lists for repeats.

    When check_unknown_keys=True, raises on state keys not matching any tool input
    or known bookkeeping key, and raises on malformed container values (non-dict
    conditionals/sections, non-list repeats).
    """
    output: dict = {}

    if check_unknown_keys:
        known = {inp.name for inp in tool_inputs}
        for key in state:
            if key not in known and key not in _NATIVE_BOOKKEEPING_KEYS:
                raise Exception(f"Unknown key found {key}, failing state validation")

    for tool_input in tool_inputs:
        parameter_type = tool_input.parameter_type
        parameter_name = tool_input.name
        value = state.get(parameter_name, None)
        state_path = flat_state_path(parameter_name, prefix)

        if parameter_type == "gx_conditional":
            conditional = cast(ConditionalParameterModel, tool_input)
            conditional_state = _as_dict(value)
            if conditional_state is None:
                if check_unknown_keys and value is not None:
                    raise Exception(
                        f"Invalid conditional state found {value!r} for conditional {parameter_name}"
                    )
                continue
            target_when = _select_which_when_native(conditional, conditional_state)
            all_params: List[ToolParameterT] = [conditional.test_parameter] + list(target_when.parameters)
            nested = walk_native_state(
                step, all_params, conditional_state, leaf_callback,
                prefix=state_path, check_unknown_keys=check_unknown_keys,
            )
            if nested:
                output[parameter_name] = nested

        elif parameter_type == "gx_repeat":
            repeat = cast(RepeatParameterModel, tool_input)
            repeat_state = _as_list(value)
            if check_unknown_keys and value is not None and not repeat_state and not isinstance(value, list):
                # _as_list returned [] but value was non-None and not already a list —
                # could be a string that didn't decode to a list, or some other type
                if isinstance(value, str):
                    try:
                        decoded = json.loads(value)
                        if not isinstance(decoded, list):
                            raise Exception(
                                f"Invalid repeat state found {value!r} for repeat {parameter_name}"
                            )
                    except (json.JSONDecodeError, TypeError):
                        raise Exception(
                            f"Invalid repeat state found {value!r} for repeat {parameter_name}"
                        )
                else:
                    raise Exception(
                        f"Invalid repeat state found {value!r} for repeat {parameter_name}"
                    )
            input_connections = step.get("input_connections", {})
            repeat_instance_connects = repeat_inputs_to_array(state_path, input_connections)
            max_instances = max(len(repeat_state), len(repeat_instance_connects))
            while len(repeat_state) < max_instances:
                repeat_state.append({})
            result_array = []
            for i, instance in enumerate(repeat_state):
                instance_prefix = f"{state_path}_{i}"
                nested = walk_native_state(
                    step, repeat.parameters, instance, leaf_callback,
                    prefix=instance_prefix, check_unknown_keys=check_unknown_keys,
                )
                result_array.append(nested)
            if result_array:
                output[parameter_name] = result_array

        elif parameter_type == "gx_section":
            section = cast(SectionParameterModel, tool_input)
            section_state = _as_dict(value)
            if section_state is None:
                if check_unknown_keys and value is not None:
                    raise Exception(
                        f"Invalid section state found {value!r} for section {parameter_name}"
                    )
                continue
            nested = walk_native_state(
                step, section.parameters, section_state, leaf_callback,
                prefix=state_path, check_unknown_keys=check_unknown_keys,
            )
            if nested:
                output[parameter_name] = nested

        else:
            result = leaf_callback(tool_input, value, state_path)
            if not isinstance(result, _SkipValue):
                output[parameter_name] = result

    return output


def _as_dict(value) -> Optional[dict]:
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        try:
            decoded = json.loads(value)
            if isinstance(decoded, dict):
                return decoded
        except (json.JSONDecodeError, TypeError):
            pass
    return None


def _as_list(value) -> list:
    if isinstance(value, list):
        return value
    if isinstance(value, str):
        try:
            decoded = json.loads(value)
            if isinstance(decoded, list):
                return decoded
        except (json.JSONDecodeError, TypeError):
            pass
    return []


def _select_which_when_native(conditional: ConditionalParameterModel, conditional_state: dict) -> ConditionalWhen:
    test_parameter = conditional.test_parameter
    test_parameter_name = test_parameter.name
    explicit_test_value = conditional_state.get(test_parameter_name)
    test_value = validate_explicit_conditional_test_value(test_parameter_name, explicit_test_value)
    target_when = None
    for when in conditional.whens:
        if test_value is None and when.is_default_when:
            target_when = when
        elif test_value == when.discriminator:
            target_when = when

    recorded_when = None
    recorded_case = conditional_state.get("__current_case__")
    if recorded_case is not None:
        if not isinstance(recorded_case, int):
            raise Exception(f"Unknown type of value for __current_case__ encountered {recorded_case}")
        if recorded_case < 0 or recorded_case >= len(conditional.whens):
            raise Exception(f"Unknown index value for __current_case__ encountered {recorded_case}")
        recorded_when = conditional.whens[recorded_case]

    if target_when is None:
        if recorded_when is not None:
            target_when = recorded_when
        else:
            for when in conditional.whens:
                if when.is_default_when:
                    target_when = when
                    break
            if target_when is None:
                raise Exception(
                    f"Cannot determine conditional branch for parameter {test_parameter_name} "
                    f"with value {explicit_test_value!r}"
                )
    if target_when and recorded_when and target_when != recorded_when:
        raise Exception(
            f"Problem parsing out tool state - inferred conflicting tool states for parameter {test_parameter_name}"
        )
    return target_when
