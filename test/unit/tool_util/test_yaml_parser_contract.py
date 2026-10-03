"""Regression matrix for authoring-model/parser disagreements in issue #23888."""

import pytest
from pydantic import ValidationError

from galaxy.tool_util.parameters.factory import (
    from_input_source,
    input_models_for_tool_source,
    UnknownParameterTypeError,
)
from galaxy.tool_util.parser.xml import XmlInputSource
from galaxy.tool_util.parser.yaml import (
    YamlInputSource,
    YamlToolSource as ParserToolSource,
)
from galaxy.tool_util.verify.parse import _matching_case_for_value
from galaxy.tool_util_models import (
    UserToolSource,
    YamlToolSource,
)
from galaxy.util import XML

MODEL_CLASSES = [UserToolSource, YamlToolSource]
DUMP_POLICIES = [
    pytest.param({}, id="full"),
    pytest.param({"exclude_none": True}, id="exclude-none"),
    pytest.param({"exclude_unset": True}, id="exclude-unset"),
]
BOOLEAN_DEFAULTS = [
    pytest.param({}, id="omitted"),
    pytest.param({"value": None}, id="null"),
    pytest.param({"value": True}, id="true"),
    pytest.param({"value": False}, id="false"),
]


def _tool(model_class, inputs=None, outputs=None):
    return model_class.model_validate(
        {
            "class": "GalaxyUserTool" if model_class is UserToolSource else "GalaxyTool",
            "id": "parser_contract",
            "name": "Parser contract",
            "version": "1.0.0",
            "container": "busybox",
            "shell_command": "true",
            "inputs": inputs or [],
            "outputs": outputs or [],
        }
    )


@pytest.mark.parametrize("model_class", MODEL_CLASSES)
@pytest.mark.parametrize(
    "optional,default,dump_policy",
    [
        pytest.param(
            optional,
            default.values[0],
            policy.values[0],
            id=f"optional-{optional}-{default.id}-{policy.id}",
            marks=(
                pytest.mark.xfail(
                    strict=True,
                    raises=AssertionError,
                    reason="#23888: sparse Boolean dump loses canonical False default for optional input",
                )
                if optional
                and (
                    (policy.id == "exclude-unset" and not default.values[0])
                    or (policy.id == "exclude-none" and default.values[0].get("value", False) is None)
                )
                else ()
            ),
        )
        for optional in (False, True)
        for default in BOOLEAN_DEFAULTS
        for policy in DUMP_POLICIES
    ],
)
def test_boolean_default_survives_model_dump_and_parser(model_class, optional, default, dump_policy):
    model = _tool(model_class, [{"name": "flag", "type": "boolean", "optional": optional, **default}])
    dumped = model.model_dump(by_alias=True, **dump_policy)
    # exclude_none deliberately removes an explicit null. Compare the meaning of
    # the emitted document, whose omitted canonical value defaults to False.
    emitted_parameter = model_class.model_validate(dumped).inputs[0].to_internal()
    parsed_parameter = input_models_for_tool_source(ParserToolSource(dumped)).parameters[0]
    assert parsed_parameter.optional is emitted_parameter.optional
    assert parsed_parameter.value is emitted_parameter.value


@pytest.mark.parametrize("model_class", MODEL_CLASSES)
@pytest.mark.parametrize("optional", [False, True])
@pytest.mark.parametrize("default", BOOLEAN_DEFAULTS)
def test_boolean_default_in_raw_canonical_definition(model_class, optional, default):
    definition = {"name": "flag", "type": "boolean", "optional": optional, **default}
    model = _tool(model_class, [definition])
    document = model.model_dump(by_alias=True, exclude_none=True)
    document["inputs"] = [definition]
    parsed_parameter = input_models_for_tool_source(ParserToolSource(document)).parameters[0]
    expected = model.inputs[0].to_internal().value
    if optional and "value" not in definition:
        # Workflow input modules use this same raw source with no default.
        expected = None
    assert parsed_parameter.value is expected


@pytest.mark.parametrize("model_class", MODEL_CLASSES)
@pytest.mark.parametrize(
    "group_type,exception",
    [
        pytest.param(
            "repeat",
            KeyError,
            id="repeat-parameters-vs-blocks",
            marks=pytest.mark.xfail(
                strict=True, raises=KeyError, reason="#23888: repeat authoring parameters are not parser blocks"
            ),
        ),
        pytest.param(
            "section",
            UnknownParameterTypeError,
            id="section-classification",
            marks=pytest.mark.xfail(
                strict=True,
                raises=UnknownParameterTypeError,
                reason="#23888: section is classified as a leaf parameter",
            ),
        ),
    ],
)
def test_structural_inputs_survive_model_dump_and_parser(model_class, group_type, exception):
    model = _tool(
        model_class,
        [{"name": "group", "type": group_type, "parameters": [{"name": "count", "type": "integer", "value": 2}]}],
    )
    expected = model.inputs[0].to_internal()
    parser = ParserToolSource(model.model_dump(by_alias=True, exclude_none=True))
    actual = input_models_for_tool_source(parser).parameters[0]
    assert actual.model_dump() == expected.model_dump()


class UnsupportedScalarOutputError(Exception):
    pass


@pytest.mark.parametrize("scalar_type", ["text", "integer", "float", "boolean"])
@pytest.mark.xfail(
    strict=True,
    reason="#23888: admin scalar outputs validate but YAML parser rejects them",
    raises=UnsupportedScalarOutputError,
)
def test_admin_scalar_outputs_survive_model_dump_and_parser(scalar_type):
    model = _tool(YamlToolSource, outputs=[{"type": scalar_type, "name": "result"}])
    try:
        outputs, collections = ParserToolSource(model.model_dump(by_alias=True, exclude_none=True)).parse_outputs(None)
    except Exception as exc:
        if type(exc) is Exception and str(exc) == f"Unknown output_type [{scalar_type}] encountered.":
            raise UnsupportedScalarOutputError(str(exc)) from exc
        raise
    assert not collections
    assert outputs["result"].type == scalar_type


@pytest.mark.parametrize("model_class", MODEL_CLASSES)
@pytest.mark.parametrize("dump_policy", [pytest.param({"exclude_unset": True}, id="unset")])
@pytest.mark.xfail(
    strict=True, reason="#23888: omitted optional=False enables XML text optionality inference", raises=AssertionError
)
def test_text_optionality_survives_sparse_model_dump(model_class, dump_policy):
    model = _tool(model_class, [{"name": "text", "type": "text"}])
    parsed_parameter = input_models_for_tool_source(
        ParserToolSource(model.model_dump(by_alias=True, **dump_policy))
    ).parameters[0]
    assert parsed_parameter.optional is model.inputs[0].to_internal().optional


@pytest.mark.parametrize(
    "model_class,output_type",
    [
        (UserToolSource, "data"),
        (UserToolSource, "collection"),
        (YamlToolSource, "collection"),
        pytest.param(
            YamlToolSource,
            "data",
            marks=pytest.mark.xfail(
                strict=True,
                raises=pytest.fail.Exception,
                reason="#23888: admin dataset output model silently discards unknown fields",
            ),
        ),
    ],
)
def test_output_unknown_fields_are_rejected(model_class, output_type):
    output = {"name": "result", "type": output_type, "from_work_dir": "result.txt", "form_work_dir": "typo"}
    if output_type == "collection":
        output = {"name": "result", "type": output_type, "collection_type": "list", "colletion_type": "typo"}
    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        _tool(model_class, outputs=[output])


@pytest.mark.parametrize("optional", [False, True])
@pytest.mark.parametrize("value,checked", [(False, True), (None, True), (True, False)])
def test_yaml_boolean_value_takes_precedence_over_checked(optional, value, checked):
    definition = {"name": "flag", "type": "boolean", "optional": optional, "value": value, "checked": checked}
    parameter = from_input_source(YamlInputSource(definition), profile=24.2)
    assert parameter.value is value


@pytest.mark.parametrize("optional", [False, True])
@pytest.mark.parametrize("checked", [None, True, False])
def test_legacy_yaml_boolean_checked_default(optional, checked):
    definition = {"name": "flag", "type": "boolean", "optional": optional, "checked": checked}
    parameter = from_input_source(YamlInputSource(definition), profile=24.2)
    assert parameter.value is checked


@pytest.mark.parametrize(
    "attributes,expected", [("optional='true'", None), ("checked='none'", None), ("checked='1'", False)]
)
def test_xml_boolean_default_preserves_factory_coercion(attributes, expected):
    parameter = from_input_source(
        XmlInputSource(XML(f'<param name="flag" type="boolean" {attributes}/>')), profile=24.2
    )
    assert parameter.value is expected


@pytest.mark.parametrize("value", [True, False])
def test_yaml_boolean_default_selects_conditional_case_in_tool_tests(value):
    definition = {
        "name": "choice",
        "type": "conditional",
        "test_parameter": {"name": "flag", "type": "boolean", "value": value},
        "whens": [
            {"discriminator": True, "parameters": [{"name": "yes", "type": "text"}]},
            {"discriminator": False, "parameters": [{"name": "no", "type": "text"}]},
        ],
    }
    document = {"id": "conditional_defaults", "inputs": [definition]}
    source = ParserToolSource(document)
    conditional = YamlInputSource(definition)
    case = _matching_case_for_value(source, conditional, conditional.parse_test_input_source(), None, False)
    assert case is not None
    discriminator, page = case
    assert discriminator == ("true" if value else "false")
    assert page.parse_input_sources()[0].parse_name() == ("yes" if value else "no")
    parameter = input_models_for_tool_source(source).parameters[0]
    assert [when.discriminator for when in parameter.whens if when.is_default_when] == [value]
