import pytest
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


# These expressions fall outside strict backend analysis. The editor's shared
# specification stays separate because its edge matching is deliberately permissive.
@pytest.mark.parametrize(
    "expression",
    [
        pytest.param('${ const inputs = {"cond|input1": true}; return inputs["cond|input1"]; }', id="const-binding"),
        pytest.param('${ let inputs = {"cond|input1": true}; return inputs["cond|input1"]; }', id="let-binding"),
        pytest.param('${ var inputs = {"cond|input1": true}; return inputs["cond|input1"]; }', id="var-binding"),
        pytest.param(
            '$(inputs = JSON.parse(\'{"cond|input1":true}\'), inputs["cond|input1"])', id="assignment-rebinding"
        ),
        pytest.param(
            '$((function (inputs) { return inputs["cond|input1"]; })({"cond|input1": true}))', id="function-binding"
        ),
        pytest.param('$(((inputs) => inputs["cond|input1"])({"cond|input1": true}))', id="arrow-binding"),
        pytest.param(
            '$({check(inputs) { return inputs["cond|input1"]; }}.check({"cond|input1": true}))', id="method-binding"
        ),
        pytest.param('$(typeof πinputs === "undefined" || πinputs["cond|input1"])', id="unicode-prefix"),
        pytest.param('$(typeof inputsπ === "undefined" || inputsπ["cond|input1"])', id="unicode-suffix"),
        pytest.param('$(inputs[`cond|${"input1"}`] === undefined)', id="interpolated-key"),
        pytest.param("$(inputs[`cond|input1`] === undefined)", id="template-key"),
        pytest.param('$(inputs[`${`inputs["cond|input1"]`}`] === undefined)', id="nested-template"),
        pytest.param('$(inputs[`a${/}/.test("") + `inputs["cond|input1"]`}`] === undefined)', id="regex-in-template"),
        pytest.param('$(inputs[`a${1 /* } */ + `inputs["cond|input1"]`}`] === undefined)', id="comment-in-template"),
        pytest.param('$(inputs["cond|\\x69nput1"] === undefined)', id="hex-escape"),
        pytest.param('$(inputs["cond|inpu\\u00741"] === undefined)', id="unicode-escape"),
    ],
)
def test_when_expressions_outside_backend_static_analysis(expression):
    analysis = analyze_input_references(expression)

    assert analysis.static_paths == []
    assert analysis.has_dynamic_inputs_access is True


@pytest.mark.parametrize(
    "expression, static_paths, dynamic",
    [
        pytest.param('$(inputs["cond|input1"][someKey] !== null)', [["cond|input1"]], True, id="computed-child"),
        pytest.param('$(inputs["cond|input1"] !== null && "=>" === "=>")', [["cond|input1"]], False, id="quoted-arrow"),
        pytest.param('$(inputs["cond|input1"][`suffix${"x"}`] !== null)', [["cond|input1"]], True, id="template-child"),
        pytest.param('$(inputs["cond|input1"]["\\x65xt"] !== null)', [["cond|input1"]], True, id="escaped-child"),
        pytest.param(
            '$(inputs["cond|input1"] !== null && inputs[`a${"b"}`] !== null)',
            [["cond|input1"]],
            True,
            id="separate-template-access",
        ),
        pytest.param(
            '$(inputs["cond|input1"].ext !== null)',
            [["cond|input1", "ext"]],
            False,
            id="static-child",
        ),
    ],
)
def test_backend_retains_proved_input_paths(expression, static_paths, dynamic):
    analysis = analyze_input_references(expression)

    assert analysis.static_paths == static_paths
    assert analysis.has_dynamic_inputs_access is dynamic
