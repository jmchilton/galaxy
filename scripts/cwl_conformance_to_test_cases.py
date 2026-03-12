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
        self.cwl_populator.run_conformance_test("""${version}""", """${doc}"""${timeout_arg})
''')

EXTENDED_TIMEOUT_TESTS: dict[str, dict[str, int]] = {
    "v1.0": {},
    "v1.1": {},
    "v1.2": {
        "simple_flat_crossproduct_scatter": 5,
    },
}

RED_TESTS = {
    "v1.0": [
        # not required
        "docker_entrypoint",
        "dockeroutputdir",
        "resreq_step_overrides_wf",
        "valuefrom_wf_step",
    ],
    "v1.1": [
        # not required
        "cwl_requirements_addition",
        "cwl_requirements_override_expression",
        "cwl_requirements_override_static",
        "docker_entrypoint",
        "dockeroutputdir",
        "inplace_update_on_dir_content",
        "networkaccess_disabled",
        "record_output_file_entry_format",
        "resreq_step_overrides_wf",
        "secondary_files_in_named_records",
        "stage_array_dirs",
        "stage_null_array",
        "stdin_shorcut",
        "symlink_to_file_out_of_workdir_illegal",
        "timelimit_expressiontool",
        "timelimit_invalid_wf",
        "valuefrom_wf_step",
        "workflow_input_inputBinding_loadContents",
        "workflow_input_loadContents_without_inputBinding",
        "workflow_step_in_loadContents",
    ],
    "v1.2": [
        # not required
        "cond-with-defaults-1",
        "cond-with-defaults-2",
        "condifional_scatter_on_nonscattered_false",
        "condifional_scatter_on_nonscattered_false_nojs",
        "condifional_scatter_on_nonscattered_true_nojs",
        "cwl_requirements_addition",
        "cwl_requirements_override_expression",
        "cwl_requirements_override_static",
        "docker_entrypoint",
        "dockeroutputdir",
        "filename_with_hash_mark",
        "illegal_symlink",
        "initial_work_dir_for_array_dirs",
        "initial_work_dir_for_null_and_arrays",
        "iwd-container-entryname1",
        "mixed_version_v12_wf",
        "modify_directory_content",
        "nested_crossproduct_nested_crossproduct_scatter",
        "nested_crossproduct_simple_scatter",
        "networkaccess_disabled",
        "record_output_file_entry_format",
        "resreq_step_overrides_wf",
        "scatter_on_scattered_conditional",
        "scatter_on_scattered_conditional_nojs",
        "secondary_files_in_named_records",
        "simple_nested_crossproduct_scatter",
        "timelimit_expressiontool",
        "valuefrom_wf_step",
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
    extended_timeout_tests = EXTENDED_TIMEOUT_TESTS.get(version, {})
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

        timeout_multiplier = extended_timeout_tests.get(id_)
        timeout_arg = f", timeout_multiplier={timeout_multiplier}" if timeout_multiplier else ""
        template_kwargs = {
            "version_simple": version_simple,
            "version": version,
            "doc": conformance_test["doc"],
            "cwl_test_def": cwl_test_def,
            "id_": id_.replace("-", "_"),
            "marks": marks,
            "timeout_arg": timeout_arg,
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
