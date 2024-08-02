import os
from typing import List

from galaxy.tool_util.parser.interface import ToolSourceTest
from galaxy.tool_util.parameters.case import test_case_state as case_state
from galaxy.tool_util.unittest_utils.parameters import (
    parameter_bundle_for_file,
    parameter_tool_source,
)
from galaxy.tool_util.parser.factory import get_tool_source
from galaxy.tool_util.unittest_utils import functional_test_tool_directory
from galaxy.tool_util.models import parse_tool


# legacy tools allows specifying parameter and repeat parameters without
# qualification. This was problematic and could result in ambigious specifications.
TOOLS_THAT_USE_UNQUALIFIED_PARAMETER_ACCESS = [
    "boolean_conditional.xml",
    "simple_constructs.xml",
    "section.xml",
    "collection_paired_conditional_structured_like.xml",
    "output_action_change_format.xml",
    "top_level_data.xml",
    "disambiguate_cond.xml",
    "multi_repeats.xml",
    "implicit_default_conds.xml",
]

# tools that use truevalue/falsevalue in parameter setting, I think we're going to
# forbid this for a future tool profile version. Potential ambigouity could result.
TOOLS_THAT_USE_TRUE_FALSE_VALUE_BOOLEAN_SPECIFICATION = [
    "inputs_as_json_profile.xml",
    "inputs_as_json_with_paths.xml",
]

TEST_TOOL_THAT_DO_NOT_VALIDATE = (
    TOOLS_THAT_USE_UNQUALIFIED_PARAMETER_ACCESS
    + TOOLS_THAT_USE_TRUE_FALSE_VALUE_BOOLEAN_SPECIFICATION
    + [
        # TODO: handle repeats
        "inputs_as_json.xml",
        "min_repeat.xml",
        "disambiguate_repeats.xml",
        "validation_repeat.xml",
        # TODO: handle multiple selects
        "validation_value_in_datatable.xml",
        "multi_select.xml",
        # TODO: handle group tags multiple and optional...
        "select_optional.xml",
        # TODO: handle data_column multiple and optional...
        "column_param_configfile.xml",
        # TODO: handle default collections
        # collection defaults not handled
        "collection_nested_default.xml",
        "collection_paired_default.xml",
        # TODO: integer_default
        "integer_default.xml",
        # will never handle upload_dataset
        "upload.xml",
    ]
)


def test_parameter_test_cases_validate():
    validate_test_cases_for("gx_int")
    warnings = validate_test_cases_for("gx_float")
    assert len(warnings[0]) == 0
    assert len(warnings[1]) == 1


VALIDATING_TOOL_NAMES = [
    "checksum.xml",
    "all_output_types.xml",
    "cheetah_casting.xml",
    "collection_creates_dynamic_list_of_pairs.xml",
    "collection_creates_dynamic_nested.xml",
    "collection_mixed_param.xml",
    "collection_type_source.xml",
]


def test_validate_framework_test_tools():
    test_tool_directory = functional_test_tool_directory()
    for tool_name in os.listdir(test_tool_directory):
        if tool_name in TEST_TOOL_THAT_DO_NOT_VALIDATE:
            continue
        if tool_name.endswith("_conf.xml"):
            # tool conf (toolbox) files or sample datatypes
            continue
        tool_path = os.path.join(test_tool_directory, tool_name)
        if not tool_path.endswith(".xml") or os.path.isdir(tool_path):
            continue

        try:
            _validate_path(tool_path)
        except Exception as e:
            raise Exception(f"Failed to validate {tool_path}: {str(e)}")


def _validate_path(tool_path: str):
    tool_source = get_tool_source(tool_path)
    parsed_tool = parse_tool(tool_source)
    profile = tool_source.parse_profile()
    test_cases: List[ToolSourceTest] = tool_source.parse_tests_to_dict(for_json=True)["tests"]
    for test_case in test_cases:
        if test_case.get("expect_failure"):
            continue
        test_case_state_and_warnings = case_state(test_case, parsed_tool.inputs, profile)
        tool_state = test_case_state_and_warnings.tool_state
        warnings = test_case_state_and_warnings.warnings
        assert tool_state.state_representation == "test_case_xml"


def validate_test_cases_for(tool_name: str) -> List[List[str]]:
    tool_parameter_bundle = parameter_bundle_for_file(tool_name)
    tool_source = parameter_tool_source(tool_name)
    profile = tool_source.parse_profile()
    test_cases: List[ToolSourceTest] = tool_source.parse_tests_to_dict(for_json=True)["tests"]
    warnings_by_test = []
    for test_case in test_cases:
        test_case_state_and_warnings = case_state(test_case, tool_parameter_bundle.input_models, profile)
        tool_state = test_case_state_and_warnings.tool_state
        warnings = test_case_state_and_warnings.warnings
        assert tool_state.state_representation == "test_case_xml"
        warnings_by_test.append(warnings)
    return warnings_by_test
