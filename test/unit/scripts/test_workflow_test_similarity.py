import sys
from pathlib import Path

import yaml

galaxy_root = Path(__file__).parent.parent.parent.parent
sys.path.insert(0, str(galaxy_root))

from scripts.workflow_test_similarity import (
    _as_mapping,
    _flatten_state,
    analyze_workflow,
    classify,
    Fingerprint,
    jaccard,
)


def _fingerprint(document: str, **kwargs) -> Fingerprint:
    fingerprint = Fingerprint(id=kwargs.pop("id", "candidate"), venue="workflow_framework", path="fixture.gxwf.yml")
    analyze_workflow(yaml.safe_load(document), fingerprint)
    for key, value in kwargs.items():
        setattr(fingerprint, key, value)
    return fingerprint


CONDITIONAL_CHAIN = """
class: GalaxyWorkflow
inputs:
  input_file:
    type: data
  should_run:
    type: boolean
outputs:
  out:
    outputSource: second/out_file1
steps:
  first:
    tool_id: cat
    in:
      input1:
        source: input_file
    when: $(inputs.should_run)
  second:
    tool_id: cat
    in:
      input1:
        source: first/out_file1
"""


def test_conditional_chain_constructs():
    fingerprint = _fingerprint(CONDITIONAL_CHAIN)
    assert "conditional_step" in fingerprint.constructs
    assert "step_chain" in fingerprint.constructs
    assert "workflow_outputs" in fingerprint.constructs
    assert fingerprint.tool_ids == {"cat"}
    assert fingerprint.step_count == 2


def test_skip_propagates_when_every_source_is_skipped():
    assert "skip_propagates" in _fingerprint(CONDITIONAL_CHAIN).constructs


def test_skip_does_not_propagate_through_a_step_that_also_reads_an_input():
    """The shape of test_expression_tool_output_in_format_source - a null is
    observed, not propagated, so it must not share the construct."""
    document = """
class: GalaxyWorkflow
inputs:
  input:
    type: data
steps:
  skip:
    tool_id: cat
    in:
      input1: input
    when: $(false)
  pick_larger:
    tool_id: expression_pick_larger_file
    in:
      input1: skip/out_file1
      input2: input
"""
    assert "skip_propagates" not in _fingerprint(document).constructs


def test_skip_does_not_propagate_through_a_null_aware_step():
    document = """
class: GalaxyWorkflow
inputs:
  input:
    type: data
steps:
  skip:
    tool_id: cat
    in:
      input1: input
    when: $(false)
  pick:
    type: pick_value
    in:
      input_0:
        source: skip/out_file1
"""
    assert "skip_propagates" not in _fingerprint(document).constructs


def test_multi_axis_mapping_needs_two_collection_inputs():
    one_axis = """
class: GalaxyWorkflow
inputs:
  list_a:
    type: collection
    collection_type: list
steps:
  the_cat:
    tool_id: cat
    in:
      input1: list_a
"""
    two_axes = """
class: GalaxyWorkflow
inputs:
  list_a:
    type: collection
    collection_type: list
  list_b:
    type: collection
    collection_type: list
steps:
  the_cat:
    tool_id: cat
    in:
      input1: list_a
      input2: list_b
"""
    assert "mapped_over" in _fingerprint(one_axis).constructs
    assert "multi_axis_mapping" not in _fingerprint(one_axis).constructs
    assert "multi_axis_mapping" in _fingerprint(two_axes).constructs


def test_subworkflow_detected_when_run_is_assembled_in_python():
    document = """
class: GalaxyWorkflow
inputs:
  collection_a: collection
steps:
  subworkflow_step:
    run: null
    in:
      collection_a: collection_a
"""
    assert "subworkflow" in _fingerprint(document).constructs


def test_nesting_depth_counts_subworkflow_levels():
    document = """
class: GalaxyWorkflow
inputs:
  text_input: text
steps:
  outer:
    run:
      class: GalaxyWorkflow
      inputs:
        inner_text: text
      steps:
        inner:
          run:
            class: GalaxyWorkflow
            inputs:
              deep_text: text
            steps:
              leaf:
                tool_id: create_2
                outputs:
                  out_file1:
                    rename: "${deep_text} out"
"""
    fingerprint = _fingerprint(document)
    assert fingerprint.nesting_depth == 2
    assert "pja:rename" in fingerprint.constructs
    assert "replacement_parameters" in fingerprint.constructs


def test_optional_input_recorded():
    document = """
class: GalaxyWorkflow
inputs:
  optional_text:
    type: text
    optional: true
steps:
  step1:
    tool_id: expression_null_handling_text
    in:
      text_input:
        source: optional_text
"""
    fingerprint = _fingerprint(document)
    assert "optional_input" in fingerprint.constructs
    assert "optional:text" in fingerprint.input_kinds


def test_state_leaves_separate_pick_value_modes():
    first_or_skip = set(_flatten_state({"mode": "first_or_skip"}))
    the_only = set(_flatten_state({"mode": "the_only_non_null"}))
    assert first_or_skip == {"state:mode=first_or_skip"}
    assert not first_or_skip & the_only


def test_flatten_state_skips_dunder_keys():
    assert set(_flatten_state({"value": {"__class__": "RuntimeValue"}})) == set()


def test_as_mapping_accepts_lists_of_labelled_dicts():
    assert _as_mapping([{"label": "a", "tool_id": "cat"}]) == {"a": {"label": "a", "tool_id": "cat"}}


def test_jaccard():
    assert jaccard({"a", "b"}, {"a", "b"}) == 1.0
    assert jaccard({"a"}, {"b"}) == 0.0
    assert jaccard(set(), set()) == 0.0


def _existing(id, constructs, tool_ids, assertion_targets, **kwargs):
    return Fingerprint(
        id=id,
        venue="workflow_framework",
        path="existing.gxwf.yml",
        constructs=set(constructs),
        tool_ids=set(tool_ids),
        assertion_targets=set(assertion_targets),
        **kwargs,
    )


def test_no_workflow_construct_belongs_as_tool_test():
    candidate = _fingerprint("""
class: GalaxyWorkflow
inputs:
  input_file:
    type: data
outputs:
  out:
    outputSource: the_cat/out_file1
steps:
  the_cat:
    tool_id: cat_data_and_sleep
    in:
      input1:
        source: input_file
""")
    verdict, _ = classify(candidate, [], [])
    assert verdict == "BELONGS_AS_TOOL_TEST"


def test_duplicate_of_an_existing_test():
    candidate = _fingerprint(CONDITIONAL_CHAIN)
    twin = _fingerprint(CONDITIONAL_CHAIN, id="already_merged")
    twin.assertion_targets.add("attr:ftype")
    verdict, why = classify(candidate, [twin], [])
    assert verdict == "DUPLICATE"
    assert "already_merged" in why


def test_new_assertion_defeats_the_duplicate_trigger():
    candidate = _fingerprint(CONDITIONAL_CHAIN)
    candidate.assertion_targets.add("attr:visible")
    twin = _fingerprint(CONDITIONAL_CHAIN, id="already_merged")
    verdict, why = classify(candidate, [twin], [])
    assert verdict == "NOVEL_ASSERTION_ONLY"
    assert "attr:visible" in why


def test_parameter_variant_on_depth_alone():
    candidate = _fingerprint(CONDITIONAL_CHAIN)
    candidate.nesting_depth = 2
    shallow = _fingerprint(CONDITIONAL_CHAIN, id="shallow")
    candidate.assertion_targets.add("attr:ftype")
    verdict, why = classify(candidate, [shallow], [])
    assert verdict == "PARAMETER_VARIANT"
    assert "nesting depth" in why


def test_novel_behavior_when_nothing_shares_the_construct_set():
    candidate = _fingerprint(CONDITIONAL_CHAIN)
    unrelated = _existing("unrelated", {"workflow_outputs"}, {"cat"}, {"has:has_text"})
    verdict, _ = classify(candidate, [unrelated], [])
    assert verdict == "NOVEL_BEHAVIOR"


def test_duplicate_of_another_proposed_test_is_named_as_such():
    candidate = _fingerprint(CONDITIONAL_CHAIN)
    sibling = _fingerprint(CONDITIONAL_CHAIN, id="also_proposed")
    sibling.assertion_targets.add("attr:ftype")
    verdict, why = classify(candidate, [], [sibling])
    assert verdict == "DUPLICATE"
    assert "also proposed" in why
