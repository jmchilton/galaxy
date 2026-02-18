"""This module is responsible for converting between Galaxy's tool
input description and the CWL description for a job json."""

import json
import logging
from enum import Enum

from galaxy.exceptions import RequestParameterInvalidException

log = logging.getLogger(__name__)

NOT_PRESENT = object()


class INPUT_TYPE(str, Enum):
    DATA = "data"
    INTEGER = "integer"
    FLOAT = "float"
    TEXT = "text"
    BOOLEAN = "boolean"
    SELECT = "select"
    FIELD = "field"
    CONDITIONAL = "conditional"
    DATA_COLLECTION = "data_collection"


# There are two approaches to mapping CWL tool state to Galaxy tool state
# one is to map CWL types to compound Galaxy tool parameters combinations
# with conditionals and the other is to use a new Galaxy parameter type that
# allows unions, optional specifications, etc.... The problem with the former
# is that it doesn't work with the workflow parameters for instance and is
# very complex on the backend. The problem with the latter is that the GUI
# for this parameter type is undefined curently.
USE_FIELD_TYPES = True

# There are two approaches to mapping CWL workflow inputs to Galaxy workflow
# steps. The first is to simply map everything to expressions and stick them into
# files and use data inputs - the second is to use parameter_input steps with
# fields types. We are dispatching on USE_FIELD_TYPES for now - to choose but
# may diverge later?
# There are open issues with each approach:
#  - Mapping everything to files makes the GUI harder to imagine but the backend
#     easier to manage in someways.
USE_STEP_PARAMETERS = USE_FIELD_TYPES


def to_galaxy_parameters(tool, as_dict):
    """Tool is Galaxy's representation of the tool and as_dict is a Galaxified
    representation of the input json (no paths, HDA references for instance).
    """
    inputs = tool.inputs
    galaxy_request = {}

    def from_simple_value(input, param_dict_value, type_representation_name=None):
        if type_representation_name == "json":
            return json.dumps(param_dict_value)
        else:
            return param_dict_value

    for input_name, input in inputs.items():
        as_dict_value = as_dict.get(input_name, NOT_PRESENT)
        galaxy_input_type = input.type

        if galaxy_input_type == "repeat":
            if input_name not in as_dict:
                continue

            only_input = next(iter(input.inputs.values()))
            for value in as_dict_value:
                key = f"{input_name}_repeat_0|{only_input.name}"
                galaxy_value = from_simple_value(only_input, value)
                galaxy_request[key] = galaxy_value
        elif galaxy_input_type == "conditional":
            case_strings = input.case_strings
            # TODO: less crazy handling of defaults...
            if (as_dict_value is NOT_PRESENT or as_dict_value is None) and "null" in case_strings:
                type_representation_name = "null"
            elif as_dict_value is NOT_PRESENT or as_dict_value is None:
                raise RequestParameterInvalidException(
                    f"Cannot translate CWL datatype - value [{as_dict_value}] of type [{type(as_dict_value)}] with case_strings [{case_strings}]. Non-null property must be set."
                )
            elif isinstance(as_dict_value, bool) and "boolean" in case_strings:
                type_representation_name = "boolean"
            elif isinstance(as_dict_value, int) and "integer" in case_strings:
                type_representation_name = "integer"
            elif isinstance(as_dict_value, int) and "long" in case_strings:
                type_representation_name = "long"
            elif isinstance(as_dict_value, (int, float)) and "float" in case_strings:
                type_representation_name = "float"
            elif isinstance(as_dict_value, (int, float)) and "double" in case_strings:
                type_representation_name = "double"
            elif isinstance(as_dict_value, str) and "string" in case_strings:
                type_representation_name = "string"
            elif (
                isinstance(as_dict_value, dict)
                and "src" in as_dict_value
                and "id" in as_dict_value
                and "file" in case_strings
            ):
                type_representation_name = "file"
            elif (
                isinstance(as_dict_value, dict)
                and "src" in as_dict_value
                and "id" in as_dict_value
                and "directory" in case_strings
            ):
                # TODO: can't disambiuate with above if both are available...
                type_representation_name = "directory"
            elif "field" in case_strings:
                type_representation_name = "field"
            elif "json" in case_strings and as_dict_value is not None:
                type_representation_name = "json"
            else:
                raise RequestParameterInvalidException(
                    f"Cannot translate CWL datatype - value [{as_dict_value}] of type [{type(as_dict_value)}] with case_strings [{case_strings}]."
                )
            galaxy_request[f"{input_name}|_cwl__type_"] = type_representation_name
            if type_representation_name != "null":
                current_case_index = input.get_current_case(type_representation_name)
                current_case_inputs = input.cases[current_case_index].inputs
                current_case_input = current_case_inputs["_cwl__value_"]
                galaxy_value = from_simple_value(current_case_input, as_dict_value, type_representation_name)
                galaxy_request[f"{input_name}|_cwl__value_"] = galaxy_value
        elif as_dict_value is NOT_PRESENT:
            continue
        else:
            galaxy_value = from_simple_value(input, as_dict_value)
            galaxy_request[input_name] = galaxy_value

    log.info(f"Converted galaxy_request is {galaxy_request}")
    return galaxy_request
