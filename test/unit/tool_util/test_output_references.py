from galaxy.tool_util.parser.output_references import (
    InputReferences,
    output_reference_problem,
)
from galaxy.tool_util.parser.xml import XmlToolSource
from galaxy.util import parse_xml_string_to_etree

TOOL = """<tool id="id" name="name">
    <inputs>
        <param name="hidden" type="hidden_data" />
        <param name="rep_1" type="data" />
        <repeat name="rep" title="Rep">
            <section name="sec" title="Sec">
                <param name="x" type="data" />
            </section>
        </repeat>
        <conditional name="cond">
            <param name="select" type="select">
                <option value="flat">Flat</option>
                <option value="nested">Nested</option>
            </param>
            <when value="flat">
                <param name="input1" type="data" />
            </when>
            <when value="nested">
                <conditional name="inner">
                    <param name="inner_select" type="select"><option value="a">a</option></param>
                    <when value="a"><param name="input1" type="data" /></when>
                </conditional>
            </when>
        </conditional>
    </inputs>
</tool>
"""


def _resolve(reference: str):
    return InputReferences(XmlToolSource(parse_xml_string_to_etree(TOOL))).resolve(reference)


def test_legacy_alias_in_repeat_keeps_its_index():
    resolved = _resolve("rep_3|x")
    assert resolved.legacy
    assert resolved.runtime_key == "rep_3|sec|x"


def test_legacy_alias_targeting_another_alias_is_kept():
    # cond|input1 is also the legacy alias of cond|inner|input1, so rewriting input1 to it would
    # resolve the nested input when the flat one is inactive.
    resolved = _resolve("input1")
    assert resolved.qualified_key == "cond|input1"
    assert resolved.runtime_key == "input1"


def test_parameter_named_like_repeat_instance():
    resolved = _resolve("rep_1")
    assert not resolved.legacy
    assert output_reference_problem(resolved, "format_source") is None


def test_hidden_data_is_a_dataset_input():
    assert output_reference_problem(_resolve("hidden"), "metadata_source") is None


def test_repeat_index_mismatch_is_not_rewritten():
    resolved = _resolve("rep_1|rep_2|x")
    assert not resolved.matches
    assert resolved.runtime_key == "rep_1|rep_2|x"


AMBIGUOUS_TOOL = """<tool id="id" name="name">
    <inputs>
        <section name="sec_a" title="A"><param name="input1" type="data" /></section>
        <section name="sec_b" title="B">
            <param name="input1" type="select"><option value="a">a</option></param>
        </section>
        <repeat name="r" title="R">
            <section name="rs" title="RS"><param name="f" type="data" /></section>
            <conditional name="rc">
                <param name="select" type="select"><option value="a">a</option></param>
                <when value="a"><param name="f" type="data" /></when>
            </conditional>
        </repeat>
    </inputs>
</tool>
"""


def test_unqualified_problem_suggests_matching_inputs_with_repeat_index():
    input_references = InputReferences(XmlToolSource(parse_xml_string_to_etree(AMBIGUOUS_TOOL)))
    unqualified = input_references.resolve("input1")
    assert output_reference_problem(unqualified, "format_source") is None
    assert output_reference_problem(unqualified, "format_source", False) == "must be qualified as 'sec_a|input1'"
    in_repeat = input_references.resolve("r_3|f")
    assert (
        output_reference_problem(in_repeat, "format_source", False) == "must be qualified as 'r_3|rc|f' or 'r_3|rs|f'"
    )
