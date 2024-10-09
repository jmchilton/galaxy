"""Test tool execution pieces.

Longer term ideally we would separate all the tool tests in test_tools.py that
describe tool execution into this file and make sure we have parallel or matching
tests for both the legacy tool execution API and the tool request API. We would then
keep things like testing other tool APIs in ./test_tools.py (index, search, tool test
files, etc..). 
"""

from galaxy_test.base.decorators import requires_tool_id
from galaxy_test.base.populators import (
    DatasetPopulator,
    TargetHistory,
)


@requires_tool_id("multi_data_param")
def test_multidata_param(target_history: TargetHistory):
    hda1 = target_history.with_dataset("1\t2\t3").src_dict
    hda2 = target_history.with_dataset("4\t5\t6").src_dict
    execution = target_history.execute("multi_data_param").with_inputs(
        {
            "f1": {"batch": False, "values": [hda1, hda2]},
            "f2": {"batch": False, "values": [hda2, hda1]},
        }
    )
    execution.assert_has_job(0).with_output("out1").with_contents("1\t2\t3\n4\t5\t6\n")
    execution.assert_has_job(0).with_output("out2").with_contents("4\t5\t6\n1\t2\t3\n")


@requires_tool_id("expression_forty_two")
def test_galaxy_expression_tool_simplest(target_history: TargetHistory):
    target_history.execute("expression_forty_two").assert_has_single_job.with_single_output.with_contents("42")


@requires_tool_id("expression_forty_two")
def test_galaxy_expression_tool_simple(target_history: TargetHistory):
    execution = target_history.execute("expression_parse_int").with_inputs({"input1": "7"})
    execution.assert_has_single_job.with_single_output.with_contents("7")


@requires_tool_id("expression_log_line_count")
def test_galaxy_expression_metadata(target_history: TargetHistory):
    hda1 = target_history.with_dataset("1\n2\n3\n4\n5\n6\n7\n8\n9\n10\n11\n12\n13\n14").src_dict
    execution = target_history.execute("expression_log_line_count").with_inputs({"input1": hda1})
    execution.assert_has_single_job.with_single_output.with_contents("3")
