import json
from typing import (
    cast,
    List,
    Optional,
)

from galaxy.tool_util.parameters import (
    ConditionalParameterModel,
    ConditionalWhen,
    flat_state_path,
    is_optional,
    repeat_inputs_to_array,
    RepeatParameterModel,
    SelectParameterModel,
    ToolParameterT,
    validate_explicit_conditional_test_value,
)
from galaxy.tool_util_models.parameters import SectionParameterModel
from galaxy.tool_util_models import ParsedTool
from ._types import (
    GetToolInfo,
    NativeStepDict,
    NativeToolStateDict,
    NativeWorkflowDict,
)


def validate_native_step_against(step: NativeStepDict, parsed_tool: ParsedTool):
    tool_state_jsonified = step.get("tool_state")
    assert tool_state_jsonified
    tool_state = json.loads(tool_state_jsonified)
    tool_inputs = parsed_tool.inputs

    # Double-encoded native format: decode per-value JSON strings
    _decode_double_encoded_values(tool_state)

    # merge input connections into ConnectedValues if there aren't already there...
    _merge_inputs_into_state_dict(step, tool_inputs, tool_state)

    allowed_extra_keys = ["__page__", "__rerun_remap_job_id__", "__job_resource", "chromInfo"]
    _validate_native_state_level(step, tool_inputs, tool_state, allowed_extra_keys=allowed_extra_keys)


def _is_connected_or_runtime(value) -> bool:
    return isinstance(value, dict) and value.get("__class__") in ("ConnectedValue", "RuntimeValue")


def _is_replacement_param(value) -> bool:
    """Check if value is a legacy replacement parameter like ${num} or #{num}."""
    if not isinstance(value, str):
        return False
    return "${" in value or "#{" in value


def _decode_double_encoded_values(state: dict):
    """Decode per-value JSON strings in a double-encoded native tool_state dict."""
    for key, value in list(state.items()):
        if isinstance(value, str):
            try:
                decoded = json.loads(value)
                state[key] = decoded
            except (json.JSONDecodeError, TypeError):
                pass  # genuinely a string value
        if isinstance(state[key], dict):
            _decode_double_encoded_values(state[key])


def _validate_native_state_level(
    step: NativeStepDict, tool_inputs: List[ToolParameterT], state_at_level: dict, allowed_extra_keys=None
):
    if allowed_extra_keys is None:
        allowed_extra_keys = []

    keys_processed = set()
    for tool_input in tool_inputs:
        parameter_name = tool_input.name
        keys_processed.add(parameter_name)
        _validate_native_state_at_level(step, tool_input, state_at_level)

    for key in state_at_level.keys():
        if key not in keys_processed and key not in allowed_extra_keys:
            raise Exception(f"Unknown key found {key}, failing state validation")


def _validate_native_state_at_level(
    step: NativeStepDict, tool_input: ToolParameterT, state_at_level: dict, prefix: Optional[str] = None
):
    parameter_type = tool_input.parameter_type
    parameter_name = tool_input.name
    value = state_at_level.get(parameter_name, None)
    state_path = flat_state_path(parameter_name, prefix)

    # ConnectedValue/RuntimeValue: valid for any parameter type
    if _is_connected_or_runtime(value):
        return

    # Scalar string-like types: pass through
    if parameter_type in [
        "gx_text",
        "gx_color",
        "gx_hidden",
        "gx_genomebuild",
        "gx_group_tag",
        "gx_baseurl",
        "gx_directory_uri",
    ]:
        pass  # string value, no strict validation needed
    elif parameter_type == "gx_integer":
        if value is not None and value != "null":
            if not _is_replacement_param(value):
                try:
                    int(value)  # type: ignore[arg-type]
                except (ValueError, TypeError):
                    raise Exception(f"Invalid integer data found {value}")
    elif parameter_type == "gx_float":
        if value is not None and value != "null":
            if not _is_replacement_param(value):
                try:
                    float(value)  # type: ignore[arg-type]
                except (ValueError, TypeError):
                    raise Exception(f"Invalid float data found {value}")
    elif parameter_type == "gx_boolean":
        pass  # native uses truevalue/falsevalue strings or bool
    elif parameter_type in ["gx_data", "gx_data_collection"]:
        if isinstance(value, dict):
            assert "__class__" in value
            assert value["__class__"] in ["RuntimeValue", "ConnectedValue"]
        else:
            assert value in [None, "null"]
            connections = native_connections_for(step, tool_input, prefix)
            # Disconnected non-optional is allowed — may be filled at runtime or model may be incomplete
    elif parameter_type == "gx_select":
        if value is not None and value != "null":
            select = cast(SelectParameterModel, tool_input)
            options = select.options
            if options is not None:
                valid_values = [o.value for o in options]
                if value not in valid_values:
                    raise Exception(f"Invalid select option found {value}")
    elif parameter_type in ["gx_data_column", "gx_drill_down"]:
        pass  # dynamic options, lenient validation
    elif parameter_type == "gx_conditional":
        conditional_state = state_at_level.get(parameter_name, None)
        if not isinstance(conditional_state, dict):
            raise Exception(f"Invalid conditional state found {conditional_state} for conditional {parameter_name}")
        conditional = cast(ConditionalParameterModel, tool_input)
        when: ConditionalWhen = _select_which_when_native(conditional, conditional_state)
        test_parameter = conditional.test_parameter
        test_parameter_name = test_parameter.name
        _validate_native_state_at_level(step, test_parameter, conditional_state, prefix=state_path)
        _validate_native_state_level(
            step, when.parameters, conditional_state, allowed_extra_keys=["__current_case__", test_parameter_name]
        )
    elif parameter_type == "gx_repeat":
        repeat = cast(RepeatParameterModel, tool_input)
        repeat_state = value
        if isinstance(repeat_state, str):
            repeat_state = json.loads(repeat_state)
        if isinstance(repeat_state, list):
            for i, instance in enumerate(repeat_state):
                instance_prefix = f"{state_path}_{i}"
                allowed = ["__index__"]
                _validate_native_state_level(step, repeat.parameters, instance, allowed_extra_keys=allowed)
        elif repeat_state is not None:
            raise Exception(f"Invalid repeat state found {repeat_state} for repeat {parameter_name}")
    elif parameter_type == "gx_section":
        section = cast(SectionParameterModel, tool_input)
        section_state = value
        if isinstance(section_state, str):
            section_state = json.loads(section_state)
        if isinstance(section_state, dict):
            _validate_native_state_level(step, section.parameters, section_state)
        elif section_state is not None:
            raise Exception(f"Invalid section state found {section_state} for section {parameter_name}")
    elif parameter_type == "gx_rules":
        pass  # complex dict, pass through
    else:
        raise NotImplementedError(f"Unhandled parameter type ({parameter_type})")


def _select_which_when_native(conditional: ConditionalParameterModel, conditional_state: dict) -> ConditionalWhen:
    test_parameter = conditional.test_parameter
    test_parameter_name = test_parameter.name
    explicit_test_value = conditional_state.get(test_parameter_name)
    test_value = validate_explicit_conditional_test_value(test_parameter_name, explicit_test_value)
    target_when = None
    for when in conditional.whens:
        # deal with native string -> bool issues in here...
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
        # If we can't determine the branch from the test value, fall back to __current_case__
        if recorded_when is not None:
            target_when = recorded_when
        else:
            # No test value match and no __current_case__ — use default when
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


def _merge_inputs_into_state_dict(
    step_dict: NativeStepDict, tool_inputs: List[ToolParameterT], state_at_level: dict, prefix: Optional[str] = None
):
    for tool_input in tool_inputs:
        _merge_into_state(step_dict, tool_input, state_at_level, prefix=prefix)


def _merge_into_state(step_dict: NativeStepDict, tool_input: ToolParameterT, state: dict, prefix: Optional[str] = None):
    name = tool_input.name
    parameter_type = tool_input.parameter_type
    state_path = flat_state_path(name, prefix)
    if parameter_type == "gx_conditional":
        conditional_state = state.get(name, {})
        if isinstance(conditional_state, str):
            conditional_state = json.loads(conditional_state)
            state[name] = conditional_state
        if name not in state:
            state[name] = conditional_state

        conditional = cast(ConditionalParameterModel, tool_input)
        when: ConditionalWhen = _select_which_when_native(conditional, conditional_state)
        test_parameter = conditional.test_parameter
        _merge_into_state(step_dict, test_parameter, conditional_state, prefix=state_path)
        for when_parameter in when.parameters:
            _merge_into_state(step_dict, when_parameter, conditional_state, prefix=state_path)
    elif parameter_type == "gx_repeat":
        repeat_state_array = state.get(name, [])
        if isinstance(repeat_state_array, str):
            repeat_state_array = json.loads(repeat_state_array)
            state[name] = repeat_state_array
        repeat = cast(RepeatParameterModel, tool_input)
        input_connections = step_dict.get("input_connections", {})
        repeat_instance_connects = repeat_inputs_to_array(state_path, input_connections)
        # Ensure we have enough instances for all connections
        max_instances = max(len(repeat_state_array), len(repeat_instance_connects))
        for i in range(max_instances):
            while len(repeat_state_array) <= i:
                repeat_state_array.append({})

            repeat_instance_prefix = f"{state_path}_{i}"
            for repeat_parameter in repeat.parameters:
                _merge_into_state(
                    step_dict,
                    repeat_parameter,
                    repeat_state_array[i],
                    prefix=repeat_instance_prefix,
                )
        if repeat_state_array and name not in state:
            state[name] = repeat_state_array
    else:
        input_connections = step_dict.get("input_connections", {})
        if state_path in input_connections and state.get(name) in (None, "null"):
            state[name] = {"__class__": "ConnectedValue"}


def validate_step_native(step: NativeStepDict, get_tool_info: GetToolInfo):
    parsed_tool = get_parsed_tool_for_native_step(step, get_tool_info)
    if parsed_tool is not None:
        validate_native_step_against(step, parsed_tool)


def get_parsed_tool_for_native_step(step: NativeStepDict, get_tool_info: GetToolInfo) -> Optional[ParsedTool]:
    tool_id = cast(str, step.get("tool_id"))
    if not tool_id:
        return None
    tool_version: Optional[str] = cast(Optional[str], step.get("tool_version"))
    parsed_tool = get_tool_info.get_tool_info(tool_id, tool_version)
    return parsed_tool


def validate_workflow_native(workflow_dict: NativeWorkflowDict, get_tool_info: GetToolInfo):
    for step_def in workflow_dict["steps"].values():
        validate_step_native(step_def, get_tool_info)


def native_tool_state(step: NativeStepDict) -> NativeToolStateDict:
    tool_state_jsonified = step.get("tool_state")
    assert tool_state_jsonified
    tool_state = json.loads(tool_state_jsonified)
    _decode_double_encoded_values(tool_state)
    return tool_state


def native_connections_for(step: NativeStepDict, parameter: ToolParameterT, prefix: Optional[str]):
    parameter_name = parameter.name
    state_path = parameter_name if prefix is None else f"{prefix}|{parameter_name}"
    input_connections = step.get("input_connections", {})
    return input_connections.get(state_path)
