import os
import string
import sys

import yaml

THIS_DIRECTORY = os.path.dirname(os.path.normpath(__file__))
API_TEST_DIRECTORY = os.path.join(THIS_DIRECTORY, "..", "..", "..", "api")

TEST_FILE_TEMPLATE = string.Template('''
"""Test CWL conformance for version $version."""

from .test_workflows_cwl import BaseCwlWorklfowTestCase


class CwlConformanceTestCase(BaseCwlWorklfowTestCase):
    """Test case mapping to CWL conformance tests for version $version."""
$tests
''')

TEST_TEMPLATE = string.Template('''
    def test_conformance_${version_simple}_${label}(self):
        """${doc}

        Generated from::

${cwl_test_def}
        """
        self.cwl_populator.run_conformance_test("""${version}""", """${doc}""")
''')

RED_TESTS = {
    "cl_basic_generation": "resource allocation mapping not implemented",
    "any_outputSource_compatibility": "Failed to find output with label [output2] in [{u'inputs': {}, u'update_time': u'2018-07-02T07:10:59.495233', u'uuid': u'1224d917-7dc7-11e8-bb8b-acde48001122', u'outputs': {}, u'history_id': u'529fd61ab1c6cc36', u'workflow_id': u'adb5f5c93f827949', u'output_collections': {}, u'state': u'scheduled', u'steps': [{u'workflow_step_label': u'input1', u'update_time': u'2018-07-02T07:10:59.499156', u'job_id': None, u'state': u'scheduled', u'workflow_step_uuid': u'a5e07f7c-d0fe-4d6d-b9cc-0657a60dbd1a', u'order_index': 0, u'action': None, u'model_class': u'WorkflowInvocationStep', u'workflow_step_id': u'adb5f5c93f827949', u'id': u'adb5f5c93f827949'}, {u'workflow_step_label': u'input2', u'update_time': u'2018-07-02T07:10:59.499750', u'job_id': None, u'state': u'scheduled', u'workflow_step_uuid': u'd7765669-6da5-4609-9f0e-a1d7f122775c', u'order_index': 1, u'action': None, u'model_class': u'WorkflowInvocationStep', u'workflow_step_id': u'529fd61ab1c6cc36', u'id': u'529fd61ab1c6cc36'}, {u'workflow_step_label': u'input3', u'update_time': u'2018-07-02T07:10:59.499996', u'job_id': None, u'state': u'scheduled', u'workflow_step_uuid': u'5c62060e-acd6-4ceb-a316-f58ad1dc6a3d', u'order_index': 2, u'action': None, u'model_class': u'WorkflowInvocationStep', u'workflow_step_id': u'd9abeb98649a6a7e', u'id': u'd9abeb98649a6a7e'}], u'model_class': u'WorkflowInvocation', u'id': u'adb5f5c93f827949'}",
    "wf_wc_scatter_multiple_merge": "AttributeError: 'EphemeralCollection' object has no attribute '_sa_instance_state'",
    "wf_wc_scatter_multiple_flattened": "EphemeralCollection no attribute",
    "wf_input_default_missing": "AttributeError: 'dict' object has no attribute 'datatype'",
    "wf_scatter_two_nested_crossproduct": "cross product not implemented",
    "wf_scatter_two_dotproduct": "AssertionError: Unimplemented scatter type [flat_crossproduct]",
    "wf_scatter_nested_crossproduct_secondempty": "not implemented",
    "wf_scatter_nested_crossproduct_firstempty": "not implemented",
    "wf_scatter_flat_crossproduct_oneempty": "#main reference",
    "step_input_default_value_nosource": "invalid location not step_input://",
    "step_input_default_value": "invalid location again",
    "step_input_default_value_nullsource": "invalid location again",
    "hints_unknown_ignored": "KeyError: 'http://example.com/BlibberBlubberFakeRequirement'",
    "initial_workdir_secondary_files_expr": "WorkflowException: Missing required secondary file 'a5c68fa5d9c04cb2f393de3ff41886497fe220c06edfaa33c52115138893587e on data 2 and data 3.idx1' from file objec",
    "schemadef_req_tool_param": "AssertionError: HelloType???",
    "schemadef_req_wf_param": "AssertionError: HelloType???",
    "param_evaluation_noexpr": """File "/Users/john/workspace/galaxy/lib/galaxy/tools/cwl/runtime_actions.py", line 191, in handle_known_output
    if output["class"] == "File":
TypeError: 'bool' object has no attribute '__getitem__'""",
}


GREEN_TESTS = [
        "170",
        "cl_gen_arrayofarrays",
        "directory_output",
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
    for i, conformance_test in enumerate(conformance_tests):
        test_with_doc = conformance_test.copy()
        del test_with_doc["doc"]
        cwl_test_def = yaml.dump(test_with_doc, default_flow_style=False)
        cwl_test_def = "\n".join(["            %s" % l for l in cwl_test_def.splitlines()])
        label = conformance_test.get("label", str(i))
        tests = tests + TEST_TEMPLATE.safe_substitute({
            'version_simple': version_simple,
            'version': version,
            'doc': conformance_test['doc'],
            'cwl_test_def': cwl_test_def,
            'label': label,
        })
        if label in GREEN_TESTS:
            green_tests = green_tests + TEST_TEMPLATE.safe_substitute({
                'version_simple': version_simple,
                'version': version,
                'doc': conformance_test['doc'],
                'cwl_test_def': cwl_test_def,
                'label': label,
            })

    test_file_contents = TEST_FILE_TEMPLATE.safe_substitute({
        'version_simple': version_simple,
        'tests': tests
    })

    green_test_file_contents = TEST_FILE_TEMPLATE.safe_substitute({
        'version_simple': version_simple,
        'tests': green_tests
    })

    with open(os.path.join(API_TEST_DIRECTORY, "test_cwl_conformance_%s.py" % version_simple), "w") as f:
        f.write(test_file_contents)
    with open(os.path.join(API_TEST_DIRECTORY, "test_cwl_conformance_green_%s.py" % version_simple), "w") as f:
        f.write(green_test_file_contents)


if __name__ == "__main__":
    main()
