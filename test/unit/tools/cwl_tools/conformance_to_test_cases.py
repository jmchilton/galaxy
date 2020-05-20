import os
import string
import sys

import yaml

THIS_DIRECTORY = os.path.dirname(os.path.normpath(__file__))
API_TEST_DIRECTORY = os.path.join(THIS_DIRECTORY, "..", "..", "..", "..", "lib", "galaxy_test", "api")

TEST_FILE_TEMPLATE = string.Template('''
"""Test CWL conformance for version $version."""

from .test_workflows_cwl import BaseCwlWorklfowTestCase


class CwlConformanceTestCase(BaseCwlWorklfowTestCase):
    """Test case mapping to CWL conformance tests for version $version."""
$tests''')

TEST_TEMPLATE = string.Template('''
    def test_conformance_${version_simple}_${label}(self):
        """${doc}

        Generated from::

${cwl_test_def}
        """  # noqa: W293
        self.cwl_populator.run_conformance_test("""${version}""", """${doc}""")
''')

RED_TESTS = {
    # NON-required:
    "wf_scatter_two_nested_crossproduct": "cross product not implemented",
    "wf_scatter_two_dotproduct": "AssertionError: Unimplemented scatter type [flat_crossproduct]",
    "wf_scatter_nested_crossproduct_secondempty": "not implemented",
    "wf_scatter_nested_crossproduct_firstempty": "not implemented",
    "wf_scatter_flat_crossproduct_oneempty": "AssertionError: Unimplemented scatter type [flat_crossproduct]",
    "format_checking": "format stuff not implemented",
    "format_checking_subclass": "format stuff not implemented",
    "format_checking_equivalentclass": "format stuff not implemented",
    "output_secondaryfile_optional": "expected null got file of size 4 (maybe null?)",
    "valuefrom_ignored_null": "wrong output, vf-concat.cwl with empty.json",
    "valuefrom_wf_step": "ValidationException: [Errno 2] No such file or directory: '/Users/john/workspace/galaxy/step_input:/1'",
    "valuefrom_wf_step_multiple": "basic.py problem ValueError: invalid literal for int() with base 10: ''",
}


GREEN_TESTS = [
    "170",
    "cl_gen_arrayofarrays",
    "docker_json_output_location",
    "docker_json_output_path",
    "envvar_req",
    "expression_any",
    "expression_any_null",
    "expression_outputEval",
    "expression_parseint",
    "exprtool_directory_literal",
    "exprtool_file_literal",
    "initial_workdir_empty_writable",
    "initial_workdir_empty_writable_docker",
    "initial_workdir_expr",
    "initial_workdir_output",
    "initial_workdir_trailingnl",
    "initialworkpath_output",
    "inline_expressions",
    "metadata",
    "nameroot_nameext_stdout_expr",
    "null_missing_params",
    "rename",
    "stdinout_redirect",
    "stdinout_redirect_docker",
    "stdout_redirect_docker",
    "stdout_redirect_mediumcut_docker",
    "stdout_redirect_shortcut_docker",
    "writable_stagedfiles",
]

GREEN_TESTS += [
    "166",
    "167",
    "any_input_param",
    "cl_optional_inputs_missing",
    "cl_optional_bindings_provided",
    "expression_any_string",
    "expression_any_nodefaultany",
    "expression_any_null_nodefaultany",
    "expression_any_nullstring_nodefaultany",
    "initworkdir_expreng_requirements",
    "nested_cl_bindings",
    "nested_prefixes_arrays",
    "nested_workflow",
    "requirement_priority",
    "requirement_override_hints",
    "requirement_workflow_steps",
    "stderr_redirect",
    "stderr_redirect_shortcut",
    "stderr_redirect_mediumcut",
    "wf_default_tool_default",
    "wf_input_default_provided",
    "wf_scatter_dotproduct_twoempty",
    "wf_wc_expressiontool",
    "wf_wc_parseInt",
    "wf_wc_scatter",
    "wf_scatter_emptylist",
    "wf_wc_nomultiple",
    "any_outputSource_compatibility",
    "wf_input_default_missing",
    "step_input_default_value_nosource",
    "step_input_default_value",
    "step_input_default_value_nullsource",
    "hints_unknown_ignored",
    "wf_wc_scatter_multiple_merge",
    "wf_wc_scatter_multiple_flattened",
    "schemadef_req_tool_param",
    "schemadef_req_wf_param",
    "param_evaluation_noexpr",
    "initial_workdir_secondary_files_expr",
    "param_evaluation_expr",
    "valuefrom_secondexpr_ignored",
    "cl_basic_generation",
    "wf_two_inputfiles_namecollision",
    "directory_input_docker",
    "input_file_literal",
    "hints_import",
    "default_path_notfound_warning",
    "wf_compound_doc",
    "shelldir_notinterpreted",
    "fileliteral_input_docker",
    "outputbinding_glob_sorted",
    "booleanflags_cl_noinputbinding",
    "outputbinding_glob_sorted",
    "success_codes",
    "cl_empty_array_input",
    "resreq_step_overrides_wf",
    "valuefrom_constant_overrides_inputs",
    "wf_step_connect_undeclared_param",
    "wf_step_access_undeclared_param",
    "expr_reference_self_noinput",
    "directory_output",
]


def main():
    version = "v1.0"
    if len(sys.argv) > 1:
        version = sys.argv[1]
    version_simple = version.replace(".", "_")
    conformance_tests_path = os.path.join(THIS_DIRECTORY, version, "conformance_tests.yaml")
    with open(conformance_tests_path, "r") as f:
        conformance_tests = yaml.load(f)

    tests = ""
    green_tests = ""
    red_tests = ""
    required_tests = ""

    for i, conformance_test in enumerate(conformance_tests):
        test_with_doc = conformance_test.copy()
        del test_with_doc["doc"]
        cwl_test_def = yaml.dump(test_with_doc, default_flow_style=False)
        cwl_test_def = "\n".join(["            %s" % l for l in cwl_test_def.splitlines()])
        label = conformance_test.get("label", str(i))
        tags = conformance_test.get("tags", [])

        template_kwargs = {
            'version_simple': version_simple,
            'version': version,
            'doc': conformance_test['doc'],
            'cwl_test_def': cwl_test_def,
            'label': label.replace("-", "_"),
        }
        tests = tests + TEST_TEMPLATE.safe_substitute(template_kwargs)
        if label in GREEN_TESTS:
            green_tests = green_tests + TEST_TEMPLATE.safe_substitute(template_kwargs)
        else:
            red_tests = red_tests + TEST_TEMPLATE.safe_substitute(template_kwargs)
        if "required" in tags:
            required_tests = required_tests + TEST_TEMPLATE.safe_substitute(template_kwargs)

    test_file_contents = TEST_FILE_TEMPLATE.safe_substitute({
        'version_simple': version_simple,
        'tests': tests
    })

    green_test_file_contents = TEST_FILE_TEMPLATE.safe_substitute({
        'version_simple': version_simple,
        'tests': green_tests
    })

    red_test_file_contents = TEST_FILE_TEMPLATE.safe_substitute({
        'version_simple': version_simple,
        'tests': red_tests
    })

    required_test_file_contents = TEST_FILE_TEMPLATE.safe_substitute({
        'version_simple': version_simple,
        'tests': required_tests
    })

    with open(os.path.join(API_TEST_DIRECTORY, "test_cwl_conformance_%s.py" % version_simple), "w") as f:
        f.write(test_file_contents)
    with open(os.path.join(API_TEST_DIRECTORY, "test_cwl_conformance_green_%s.py" % version_simple), "w") as f:
        f.write(green_test_file_contents)
    with open(os.path.join(API_TEST_DIRECTORY, "test_cwl_conformance_red_%s.py" % version_simple), "w") as f:
        f.write(red_test_file_contents)
    with open(os.path.join(API_TEST_DIRECTORY, "test_cwl_conformance_required_%s.py" % version_simple), "w") as f:
        f.write(required_test_file_contents)


if __name__ == "__main__":
    main()
