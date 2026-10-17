import json
from typing import (
    Any,
    Literal,
)

from pydantic import ValidationError

from galaxy.exceptions import RequestParameterInvalidException
from galaxy.tool_util_models.parameter_validators import DiscriminatedAnyValidatorModel
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


# Parameter types whose editor form has regex rows or a min/max pair.
FORM_REGEX_PARAMETER_TYPES = ("text", "directory_uri")
FORM_RANGE_PARAMETER_TYPES = ("integer", "float")


def validators_to_form(parameter_type: str, validators: list[dict[str, Any]]) -> dict[str, Any]:
    """Persisted validators as editor form values.

    Regex rows, the first min/max pair, and the rest unchanged in the hidden ``extra_validators`` field.
    """
    form: dict[str, Any] = {"validators": []}
    extra: list[dict[str, Any]] = []
    for validator in validators:
        if parameter_type in FORM_REGEX_PARAMETER_TYPES and _is_form_regex(validator):
            form["validators"].append(
                {"regex_doc": validator.get("message"), "regex_match": validator.get("expression")}
            )
        elif (
            "min" not in form
            and parameter_type in FORM_RANGE_PARAMETER_TYPES
            and _is_form_range(parameter_type, validator)
        ):
            form["min"] = validator.get("min")
            form["max"] = validator.get("max")
        else:
            extra.append(validator)
    if extra:
        form["extra_validators"] = json.dumps(extra)
    return form


def validators_from_form(parameter_definition: dict[str, Any]) -> list[dict[str, Any]]:
    """Inverse of :func:`validators_to_form`: editor form values as persisted validators."""
    validators: list[dict[str, Any]] = []
    min = parameter_definition.get("min")
    max = parameter_definition.get("max")
    if min is not None or max is not None:
        validators.append({"min": min, "max": max, "negate": False, "type": "in_range"})
    for row in parameter_definition.get("validators") or []:
        validators.append(
            {"message": row["regex_doc"], "expression": row["regex_match"], "negate": False, "type": "regex"}
        )
    validators.extend(_load_extra_validators(parameter_definition.get("extra_validators")))
    return validators


def _non_default_keys(validator: dict[str, Any]) -> set[str] | None:
    """Keys of ``validator`` set to something other than its model's default; None if it does not parse."""
    try:
        model_fields = type(DiscriminatedAnyValidatorModel.validate_python(validator)).model_fields
    except ValidationError:
        return None
    return {
        key
        for key, value in validator.items()
        if value is not None and (key not in model_fields or value != model_fields[key].default)
    }


def _is_form_regex(validator: dict[str, Any]) -> bool:
    keys = _non_default_keys(validator) if validator.get("type") == "regex" else None
    return keys is not None and keys <= {"expression", "message"}


def _is_form_range(parameter_type: str, validator: dict[str, Any]) -> bool:
    keys = _non_default_keys(validator) if validator.get("type") == "in_range" else None
    if keys is None or not keys <= {"min", "max"}:
        return False
    # integer inputs' min/max fields would truncate fractional bounds
    return parameter_type != "integer" or all(
        isinstance(validator.get(key), (int, type(None))) for key in ("min", "max")
    )


def _load_extra_validators(value: str | None) -> list[dict[str, Any]]:
    if not value:
        return []
    try:
        validators = json.loads(value)
    except ValueError:
        validators = None
    if not isinstance(validators, list) or not all(isinstance(v, dict) for v in validators):
        raise RequestParameterInvalidException("Workflow parameter extra_validators must be a JSON list.")
    return validators
