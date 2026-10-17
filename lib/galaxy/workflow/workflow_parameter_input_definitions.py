from typing import (
    Any,
    Literal,
)

from galaxy.tools.parameters.basic import (
    BooleanToolParameter,
    ColorToolParameter,
    DirectoryUriToolParameter,
    FloatToolParameter,
    IntegerToolParameter,
    TextToolParameter,
)

INPUT_PARAMETER_TYPES = Literal["text", "integer", "float", "boolean", "color", "directory_uri"]
default_source_type = dict[str, int | float | bool | str]
tool_param_type = (
    TextToolParameter
    | IntegerToolParameter
    | FloatToolParameter
    | BooleanToolParameter
    | ColorToolParameter
    | DirectoryUriToolParameter
)


def get_default_parameter(param_type: INPUT_PARAMETER_TYPES, multiple: bool = False) -> tool_param_type:
    """
    param_type is the type of parameter we want to build up, stored_parameter_type is the parameter_type
    as stored in the tool state. ``multiple`` applies to integer, float and text parameters.
    """
    default_source: default_source_type = dict(name="default", label="Default Value", type=param_type, optional=False)
    if param_type in ("integer", "float", "text") and multiple:
        default_source["multiple"] = True
    if param_type == "text":
        input_default_value: tool_param_type = TextToolParameter(None, default_source)
    elif param_type == "integer":
        input_default_value = IntegerToolParameter(None, default_source)
    elif param_type == "float":
        input_default_value = FloatToolParameter(None, default_source)
    elif param_type == "boolean":
        input_default_value = BooleanToolParameter(None, default_source)
    elif param_type == "color":
        input_default_value = ColorToolParameter(None, default_source)
    elif param_type == "directory_uri":
        input_default_value = DirectoryUriToolParameter(None, default_source)
    return input_default_value


def validators_to_form(validators: list[dict[str, Any]]) -> dict[str, Any]:
    """Persisted validators as editor form values: regex rows and a min/max pair."""
    form: dict[str, Any] = {"validators": []}
    for validator in validators:
        validator_type = validator["type"]
        if validator_type == "regex":
            form["validators"].append(
                {"regex_doc": validator.get("message"), "regex_match": validator.get("expression")}
            )
        elif validator_type == "in_range":
            form["min"] = validator.get("min")
            form["max"] = validator.get("max")
    return form


def validators_from_form(parameter_definition: dict[str, Any]) -> list[dict[str, Any]]:
    """Inverse of :func:`validators_to_form`: editor form values as persisted validators."""
    validators: list[dict[str, Any]] = []
    if "min" in parameter_definition or "max" in parameter_definition:
        min = parameter_definition.get("min")
        max = parameter_definition.get("max")
        validators.append({"min": min, "max": max, "negate": False, "type": "in_range"})
    if "validators" in parameter_definition:
        for row in parameter_definition["validators"]:
            validators.append(
                {"message": row["regex_doc"], "expression": row["regex_match"], "negate": False, "type": "regex"}
            )
    return validators
