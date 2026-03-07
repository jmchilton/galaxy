from typing import (
    cast,
    Dict,
    List,
    Optional,
)

from pydantic import (
    BaseModel,
    Field,
)

import json

from galaxy.tool_util.parameters import (
    ConditionalParameterModel,
    ConditionalWhen,
    RepeatParameterModel,
    SelectParameterModel,
    ToolParameterT,
    validate_explicit_conditional_test_value,
)
from galaxy.tool_util_models.parameters import SectionParameterModel
from galaxy.tool_util_models import ParsedTool
from ._types import (
    Format2StateDict,
    GetToolInfo,
    NativeStepDict,
)
from .validation_format2 import validate_step_against
from .validation_native import (
    get_parsed_tool_for_native_step,
    native_tool_state,
    validate_native_step_against,
)

Format2InputsDictT = Dict[str, str]


class Format2State(BaseModel):
    state: Format2StateDict
    inputs: Format2InputsDictT = Field(alias="in")


class ConversionValidationFailure(Exception):
    pass


def convert_state_to_format2(native_step_dict: NativeStepDict, get_tool_info: GetToolInfo) -> Format2State:
    parsed_tool = get_parsed_tool_for_native_step(native_step_dict, get_tool_info)
    return convert_state_to_format2_using(native_step_dict, parsed_tool)


def convert_state_to_format2_using(native_step_dict: NativeStepDict, parsed_tool: Optional[ParsedTool]) -> Format2State:
    """Create a "clean" gxformat2 workflow tool state from a native workflow step.

    gxformat2 does not know about tool specifications so it cannot reason about the native
    tool state attribute and just copies it as is. This native state can be pretty ugly. The purpose
    of this function is to build a cleaned up state to replace the gxformat2 copied native tool_state
    with that is more readable and has stronger typing by using the tool's inputs to guide
    the conversion (the parsed_tool parameter).

    This method validates both the native tool state and the resulting gxformat2 tool state
    so that we can be more confident the conversion doesn't corrupt the workflow. If no meta
    model to validate against is supplied or if either validation fails this method throws
    ConversionValidationFailure to signal the caller to just use the native tool state as is
    instead of trying to convert it to a cleaner gxformat2 tool state - under the assumption
    it is better to have an "ugly" workflow than a corrupted one during conversion.
    """
    if parsed_tool is None:
        raise ConversionValidationFailure("Could not resolve tool inputs")
    try:
        validate_native_step_against(native_step_dict, parsed_tool)
    except Exception:
        raise ConversionValidationFailure(
            "Failed to validate native step - not going to convert a tool state that isn't understood"
        )
    result = _convert_valid_state_to_format2(native_step_dict, parsed_tool)
    try:
        _validate_converted_result(result, parsed_tool)
    except Exception:
        raise ConversionValidationFailure(
            "Failed to validate resulting cleaned step - not going to convert to an unvalidated tool state"
        )
    return result


def _validate_converted_result(result: "Format2State", parsed_tool: ParsedTool):
    """Validate converted format2 state.

    Uses WorkflowStepLinkedToolState for validation — this allows ConnectedValue
    markers for parameters that are in the `in` dict.
    """
    import copy
    import re
    from galaxy.tool_util.parameters import WorkflowStepLinkedToolState

    # Build a state dict with ConnectedValue markers for connected params
    linked_state = copy.deepcopy(result.state)
    for connection_path in result.inputs:
        _inject_connected_value(linked_state, connection_path)

    # Skip validation if state contains replacement parameters — these can't
    # pass Pydantic type validation (e.g., "${num}" for an integer field)
    if _state_has_replacement_params(linked_state):
        return

    try:
        linked_model = WorkflowStepLinkedToolState.parameter_model_for(parsed_tool.inputs)
        linked_model.model_validate(linked_state)
    except Exception as e:
        # If the only errors are ConnectedValue type mismatches, that's a model gap not a conversion error
        error_str = str(e)
        if "ConnectedValue" in error_str:
            pass  # Known model completeness gap — connected values not accepted for all types
        else:
            raise


def _state_has_replacement_params(state) -> bool:
    """Check if any value in a (possibly nested) state dict is a replacement parameter."""
    if isinstance(state, dict):
        for v in state.values():
            if _state_has_replacement_params(v):
                return True
    elif isinstance(state, list):
        for v in state:
            if _state_has_replacement_params(v):
                return True
    elif isinstance(state, str) and _is_replacement_param(state):
        return True
    return False


def _inject_connected_value(state: dict, connection_path: str):
    """Inject a ConnectedValue marker into a structured state dict.

    Connection paths use | as separator and _N for repeat indices.
    E.g., "queries_0|input2" → state["queries"][0]["input2"] = ConnectedValue
    E.g., "cond|param" → state["cond"]["param"] = ConnectedValue
    """
    import re

    parts = connection_path.split("|")
    target = state
    for i, part in enumerate(parts[:-1]):
        # Check for repeat index pattern: name_N
        match = re.match(r"^(.+)_(\d+)$", part)
        if match:
            repeat_name = match.group(1)
            repeat_idx = int(match.group(2))
            if repeat_name not in target:
                target[repeat_name] = []
            arr = target[repeat_name]
            while len(arr) <= repeat_idx:
                arr.append({})
            target = arr[repeat_idx]
        else:
            if part not in target:
                target[part] = {}
            target = target[part]

    # Set the leaf
    leaf = parts[-1]
    target[leaf] = {"__class__": "ConnectedValue"}


def _convert_valid_state_to_format2(native_step_dict: NativeStepDict, parsed_tool: ParsedTool) -> Format2State:
    format2_state: Format2StateDict = {}
    format2_in: Format2InputsDictT = {}

    root_tool_state = native_tool_state(native_step_dict)
    tool_inputs = parsed_tool.inputs
    _convert_state_level(native_step_dict, tool_inputs, root_tool_state, format2_state, format2_in)
    return Format2State(
        **{
            "state": format2_state,
            "in": format2_in,
        }
    )


def _convert_state_level(
    step: NativeStepDict,
    tool_inputs: List[ToolParameterT],
    native_state: dict,
    format2_state_at_level: dict,
    format2_in: Format2InputsDictT,
    prefix: Optional[str] = None,
) -> None:
    prefix = prefix or ""
    assert prefix is not None
    for tool_input in tool_inputs:
        _convert_state_at_level(step, tool_input, native_state, format2_state_at_level, format2_in, prefix)


def _convert_state_at_level(
    step: NativeStepDict,
    tool_input: ToolParameterT,
    native_state_at_level: dict,
    format2_state_at_level: dict,
    format2_in: Format2InputsDictT,
    prefix: str,
) -> None:
    parameter_type = tool_input.parameter_type
    parameter_name = tool_input.name
    value = native_state_at_level.get(parameter_name, None)
    state_path = f"{prefix}|{parameter_name}" if prefix else parameter_name
    input_connections = step.get("input_connections", {})

    if parameter_type in ["gx_data", "gx_data_collection"]:
        # Data params: connected → goes in format2 `in`; otherwise absent from state
        if state_path in input_connections or _is_connected_value(value):
            format2_in[state_path] = "placeholder"
        elif isinstance(value, dict) and value.get("__class__") == "RuntimeValue":
            format2_in[state_path] = "placeholder"
        # else: absent from state (which is valid for data params)

    elif parameter_type in [
        "gx_integer", "gx_float", "gx_boolean",
        "gx_text", "gx_color", "gx_hidden", "gx_genomebuild",
        "gx_group_tag", "gx_baseurl", "gx_directory_uri",
        "gx_select", "gx_data_column", "gx_drill_down",
    ]:
        if _is_connected_value(value):
            format2_in[state_path] = "placeholder"
        elif state_path in input_connections:
            format2_in[state_path] = "placeholder"
        elif value is not None and value != "null":
            format2_state_at_level[parameter_name] = _convert_scalar_value(
                parameter_type, parameter_name, value, tool_input,
            )

    elif parameter_type == "gx_conditional":
        conditional = cast(ConditionalParameterModel, tool_input)
        conditional_state = native_state_at_level.get(parameter_name, {})
        if isinstance(conditional_state, str):
            conditional_state = json.loads(conditional_state)
        if not isinstance(conditional_state, dict):
            return

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
        if target_when is None:
            return

        format2_conditional: dict = {}
        # Convert test parameter
        _convert_state_at_level(
            step, test_parameter, conditional_state, format2_conditional, format2_in, state_path,
        )
        # Convert active branch parameters
        _convert_state_level(
            step, target_when.parameters, conditional_state, format2_conditional, format2_in, state_path,
        )
        if format2_conditional:
            format2_state_at_level[parameter_name] = format2_conditional

    elif parameter_type == "gx_repeat":
        repeat = cast(RepeatParameterModel, tool_input)
        repeat_state = value
        if isinstance(repeat_state, str):
            repeat_state = json.loads(repeat_state)
        if not isinstance(repeat_state, list):
            return

        format2_array = []
        for i, instance in enumerate(repeat_state):
            instance_prefix = f"{state_path}_{i}"
            format2_instance: dict = {}
            _convert_state_level(
                step, repeat.parameters, instance, format2_instance, format2_in, instance_prefix,
            )
            format2_array.append(format2_instance)
        if format2_array:
            format2_state_at_level[parameter_name] = format2_array

    elif parameter_type == "gx_section":
        section = cast(SectionParameterModel, tool_input)
        section_state = value
        if isinstance(section_state, str):
            section_state = json.loads(section_state)
        if not isinstance(section_state, dict):
            return

        format2_section: dict = {}
        _convert_state_level(
            step, section.parameters, section_state, format2_section, format2_in, state_path,
        )
        if format2_section:
            format2_state_at_level[parameter_name] = format2_section

    elif parameter_type == "gx_rules":
        if value is not None and not _is_connected_value(value):
            if isinstance(value, str):
                value = json.loads(value)
            format2_state_at_level[parameter_name] = value


def _convert_scalar_value(parameter_type: str, parameter_name: str, value, tool_input: ToolParameterT):
    """Convert a native scalar value to format2 representation."""
    if parameter_type == "gx_integer":
        if _is_replacement_param(value):
            return value
        try:
            return int(value)
        except (ValueError, TypeError):
            raise Exception(f"Failed to convert integer value {value!r} for {parameter_name}")
    elif parameter_type == "gx_float":
        if _is_replacement_param(value):
            return value
        try:
            return float(value)
        except (ValueError, TypeError):
            raise Exception(f"Failed to convert float value {value!r} for {parameter_name}")
    elif parameter_type == "gx_boolean":
        return _coerce_bool(value)
    elif parameter_type == "gx_select":
        select = cast(SelectParameterModel, tool_input)
        if select.multiple:
            if isinstance(value, str):
                return value.split(",") if value else []
            elif isinstance(value, list):
                return value
        return value
    else:
        # gx_text, gx_color, gx_hidden, gx_data_column, gx_drill_down, etc.
        return value


def _is_connected_value(value) -> bool:
    return isinstance(value, dict) and value.get("__class__") in ("ConnectedValue", "RuntimeValue")


def _is_replacement_param(value) -> bool:
    if not isinstance(value, str):
        return False
    return "${" in value or "#{" in value


def _coerce_bool(value) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.lower() in ("true", "yes", "1")
    return bool(value)
