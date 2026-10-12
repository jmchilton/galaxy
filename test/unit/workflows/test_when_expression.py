import yaml

from galaxy.util.resources import resource_string
from galaxy.workflow.when_expression import analyze_input_references


def test_shared_when_expression_spec():
    cases = yaml.safe_load(resource_string("galaxy.workflow", "when_expression_spec.yml"))

    for case in cases:
        expected = case["expect"]
        # Input-to-edge matching is client policy. This backend contract only
        # covers the reference-analysis expectations in the shared fixture.
        if "static_paths" not in expected and "dynamic" not in expected:
            continue
        analysis = analyze_input_references(case["expression"])

        if "static_paths" in expected:
            assert analysis.static_paths == expected["static_paths"], case["doc"]
        if "dynamic" in expected:
            assert analysis.has_dynamic_inputs_access is expected["dynamic"], case["doc"]
