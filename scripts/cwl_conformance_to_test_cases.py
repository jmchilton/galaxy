import os
import string
import sys

import yaml

sys.path.insert(0, os.path.join(os.path.dirname(os.path.realpath(__file__)), os.pardir, "lib"))
from galaxy.tool_util.unittest_utils.cwl_data import conformance_tests_gen

THIS_DIRECTORY = os.path.dirname(os.path.realpath(__file__))
GALAXY_ROOT_DIR = os.path.abspath(os.path.join(THIS_DIRECTORY, os.pardir))
CWL_API_TESTS_DIRECTORY = os.path.join(GALAXY_ROOT_DIR, "lib", "galaxy_test", "api", "cwl")

TEST_FILE_TEMPLATE = string.Template('''"""Test CWL conformance for version ${version}."""

import pytest

from ..test_workflows_cwl import BaseCwlWorkflowsApiTestCase


class TestCwlConformance(BaseCwlWorkflowsApiTestCase):
    """Test case mapping to CWL conformance tests for version ${version}."""
$tests''')

TEST_TEMPLATE = string.Template('''
${marks}    def test_conformance_${version_simple}_${id_}(self):
        """${doc}

        Generated from::

${cwl_test_def}
        """  # noqa: W293
        self.cwl_populator.run_conformance_test("""${version}""", """${doc}""")
''')

RED_TESTS = {
    "v1.0": [
        # not required
        "docker_entrypoint",
        "dockeroutputdir",
        "initialworkdir_nesteddir",
        "input_dir_recurs_copy_writable",
        "resreq_step_overrides_wf",
        "valuefrom_wf_step",
        "wf_scatter_flat_crossproduct_oneempty",
        "wf_scatter_nested_crossproduct_firstempty",
        "wf_scatter_nested_crossproduct_secondempty",
        "wf_scatter_two_flat_crossproduct",
        "wf_scatter_two_nested_crossproduct",
        "wf_scatter_twoparam_dotproduct_valuefrom",
        "wf_scatter_twoparam_flat_crossproduct_valuefrom",
        "wf_scatter_twoparam_nested_crossproduct_valuefrom",
        "workflow_file_input_default_unspecified",
    ],
    "v1.1": [
        # required
        "input_records_file_entry_with_format",
        "outputEval_exitCode",
        "outputbinding_glob_directory",
        "secondary_files_missing",
        "stage_file_array_to_dir",
        "stage_file_array_to_dir_basename",
        "stage_file_array_to_dir_basename_entryname",
        # not required
        "cwl_requirements_addition",
        "cwl_requirements_override_expression",
        "cwl_requirements_override_static",
        "docker_entrypoint",
        "dockeroutputdir",
        "embedded_subworkflow",
        "initialworkdir_nesteddir",
        "inplace_update_on_dir_content",
        "input_dir_recurs_copy_writable",
        "networkaccess_disabled",
        "record_output_file_entry_format",
        "resreq_step_overrides_wf",
        "scatter_embedded_subworkflow",
        "scatter_multi_input_embedded_subworkflow",
        "secondary_files_in_named_records",
        "stage_array_dirs",
        "stage_null_array",
        "stdin_shorcut",
        "symlink_to_file_out_of_workdir_illegal",
        "timelimit_expressiontool",
        "timelimit_invalid_wf",
        "valuefrom_wf_step",
        "wf_scatter_flat_crossproduct_oneempty",
        "wf_scatter_nested_crossproduct_firstempty",
        "wf_scatter_nested_crossproduct_secondempty",
        "wf_scatter_two_flat_crossproduct",
        "wf_scatter_two_nested_crossproduct",
        "wf_scatter_twoparam_dotproduct_valuefrom",
        "wf_scatter_twoparam_flat_crossproduct_valuefrom",
        "wf_scatter_twoparam_nested_crossproduct_valuefrom",
        "workflow_embedded_subworkflow_embedded_subsubworkflow",
        "workflow_embedded_subworkflow_with_subsubworkflow_and_tool",
        "workflow_embedded_subworkflow_with_tool_and_subsubworkflow",
        "workflow_file_input_default_unspecified",
        "workflow_input_inputBinding_loadContents",
        "workflow_input_loadContents_without_inputBinding",
        "workflow_step_in_loadContents",
    ],
    "v1.2": [
        # required
        "stage_file_array",
        "stage_file_array_basename",
        "stage_file_array_entryname_overrides",
        # not required
        "all_non_null_all_null",
        "all_non_null_all_null_nojs",
        "all_non_null_multi_non_null",
        "all_non_null_multi_non_null_nojs",
        "all_non_null_one_non_null",
        "all_non_null_one_non_null_nojs",
        "capture_dirs",
        "capture_files",
        "capture_files_and_dirs",
        "colon_in_output_path",
        "colon_in_paths",
        "cond-with-defaults-1",
        "cond-with-defaults-2",
        "condifional_scatter_on_nonscattered_false",
        "condifional_scatter_on_nonscattered_false_nojs",
        "condifional_scatter_on_nonscattered_true_nojs",
        "conditionals_multi_scatter",
        "conditionals_multi_scatter_nojs",
        "conditionals_nested_cross_scatter",
        "conditionals_nested_cross_scatter_nojs",
        "cwl_requirements_addition",
        "cwl_requirements_override_expression",
        "cwl_requirements_override_static",
        "cwloutput_nolimit",
        "directory_literal_with_literal_file_in_subdir_nostdin",
        "docker_entrypoint",
        "dockeroutputdir",
        "dotproduct_dotproduct_scatter",
        "dotproduct_simple_scatter",
        "embedded_subworkflow",
        "filename_with_hash_mark",
        "first_non_null_first_non_null",
        "first_non_null_first_non_null_nojs",
        "first_non_null_second_non_null",
        "first_non_null_second_non_null_nojs",
        "flat_crossproduct_flat_crossproduct_scatter",
        "flat_crossproduct_simple_scatter",
        "illegal_symlink",
        "initial_work_dir_for_array_dirs",
        "initial_work_dir_for_null_and_arrays",
        "initialworkdir_nesteddir",
        "input_dir_recurs_copy_writable",
        "iwd-container-entryname1",
        "iwd-fileobjs1",
        "iwd-fileobjs2",
        "length_for_non_array",
        "mixed_version_v12_wf",
        "modify_directory_content",
        "nested_crossproduct_nested_crossproduct_scatter",
        "nested_crossproduct_simple_scatter",
        "nested_types",
        "networkaccess_disabled",
        "output_reference_workflow_input",
        "paramref_arguments_inputs",
        "paramref_arguments_self",
        "params_broken_null",
        "pass_through_required_false_when",
        "pass_through_required_false_when_nojs",
        "pass_through_required_the_only_non_null",
        "pass_through_required_the_only_non_null_nojs",
        "pass_through_required_true_when",
        "pass_through_required_true_when_nojs",
        "record_order_with_input_bindings",
        "record_output_file_entry_format",
        "record_outputeval_nojs",
        "record_with_default",
        "resreq_step_overrides_wf",
        "scatter_embedded_subworkflow",
        "scatter_multi_input_embedded_subworkflow",
        "scatter_on_scattered_conditional",
        "scatter_on_scattered_conditional_nojs",
        "schemadef_types_with_import",
        "secondary_files_in_named_records",
        "simple_dotproduct_scatter",
        "simple_flat_crossproduct_scatter",
        "simple_nested_crossproduct_scatter",
        "simple_simple_scatter",
        "storage_float",
        "the_only_non_null_single_true",
        "the_only_non_null_single_true_nojs",
        "timelimit_expressiontool",
        "user_defined_length_in_parameter_reference",
        "valuefrom_wf_step",
        "very_big_and_very_floats_nojs",
        "wf_scatter_flat_crossproduct_oneempty",
        "wf_scatter_nested_crossproduct_firstempty",
        "wf_scatter_nested_crossproduct_secondempty",
        "wf_scatter_two_flat_crossproduct",
        "wf_scatter_two_nested_crossproduct",
        "wf_scatter_twoparam_dotproduct_valuefrom",
        "wf_scatter_twoparam_flat_crossproduct_valuefrom",
        "wf_scatter_twoparam_nested_crossproduct_valuefrom",
        "wf_wc_nomultiple_merge_nested",
        "workflow_embedded_subworkflow_embedded_subsubworkflow",
        "workflow_embedded_subworkflow_with_subsubworkflow_and_tool",
        "workflow_embedded_subworkflow_with_tool_and_subsubworkflow",
        "workflow_file_input_default_unspecified",
        "workflow_input_inputBinding_loadContents",
        "workflow_input_loadContents_without_inputBinding",
        "workflow_step_in_loadContents",
    ],
}


def main():
    if len(sys.argv) != 3:
        raise Exception("Expecting 2 arguments: conformance_tests_dir version")
    conformance_tests_dir = sys.argv[1]
    version = sys.argv[2]
    version_simple = version.replace(".", "_")

    red_tests_list = RED_TESTS[version]
    red_tests_found = set()
    all_tests_found = set()

    tests = ""

    for i, conformance_test in enumerate(conformance_tests_gen(os.path.join(conformance_tests_dir, version))):
        test_with_doc = conformance_test.copy()
        if "doc" not in test_with_doc:
            raise Exception(f"No doc in test [{test_with_doc}]")
        del test_with_doc["doc"]
        cwl_test_def = yaml.dump(test_with_doc, default_flow_style=False)
        cwl_test_def = "\n".join(f"            {line}" for line in cwl_test_def.splitlines())
        id_ = conformance_test.get("id", str(i))
        tags = conformance_test.get("tags", [])
        is_red = id_ in red_tests_list

        marks = "    @pytest.mark.cwl_conformance\n"
        marks += f"    @pytest.mark.cwl_conformance_{version_simple}\n"
        for tag in tags:
            marks += f"    @pytest.mark.{tag}\n"
        if is_red:
            marks += "    @pytest.mark.red\n"
        else:
            marks += "    @pytest.mark.green\n"

        if not {"command_line_tool", "expression_tool", "workflow"}.intersection(tags):
            print(
                f"PROBLEM - test [{id_}] tagged with neither command_line_tool, expression_tool, nor workflow",
                file=sys.stderr,
            )

        template_kwargs = {
            "version_simple": version_simple,
            "version": version,
            "doc": conformance_test["doc"],
            "cwl_test_def": cwl_test_def,
            "id_": id_.replace("-", "_"),
            "marks": marks,
        }
        test_body = TEST_TEMPLATE.safe_substitute(template_kwargs)
        tests += test_body

        if id_ in all_tests_found:
            print(f"PROBLEM - Duplicate id found [{id_}]", file=sys.stderr)
        all_tests_found.add(id_)
        if is_red:
            red_tests_found.add(id_)

    test_file_contents = TEST_FILE_TEMPLATE.safe_substitute(
        {
            "version": version,
            "version_simple": version_simple,
            "tests": tests,
        }
    )

    test_file = os.path.join(CWL_API_TESTS_DIRECTORY, f"test_cwl_conformance_{version_simple}.py")
    with open(test_file, "w") as f:
        f.write(test_file_contents)
    print(f"Finished writing {test_file}")

    for red_test in red_tests_list:
        if red_test not in red_tests_found:
            print(f"PROBLEM - Failed to find annotated red test [{red_test}]", file=sys.stderr)


if __name__ == "__main__":
    main()
