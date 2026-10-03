"""Authoring contracts exercised by forms and jobs from raw YAML/JSON sources."""

from pathlib import Path

import pytest

from galaxy_test.base.decorators import requires_tool_id
from galaxy_test.base.populators import (
    DatasetPopulator,
    DescribeToolInputs,
    DescribeUserTool,
    RequiredTool,
)

TOOL_DIR = Path(__file__).resolve().parents[3] / "test" / "functional" / "tools"
SOURCE_DIR = Path(__file__).resolve().parents[1] / "base" / "data" / "user_tools"
BOOLEAN_DEFAULTS = {
    "required_true": True,
    "required_false": False,
    "required_omitted": False,
    "optional_true": True,
    "optional_false": False,
}
BOOLEAN_OVERRIDES = {
    "required_true": False,
    "required_false": True,
    "required_omitted": True,
    "optional_true": None,
    "optional_false": True,
}


class InferredOptionality(Exception):
    pass


class MissingOptionalBooleanDefault(Exception):
    pass


class RequestNullBooleanDefault(Exception):
    pass


def _sources(tool_id, yaml_directory=TOOL_DIR / "parameters"):
    return [
        pytest.param(yaml_directory / f"{tool_id}.yml", id=f"{tool_id}-yaml"),
        pytest.param(SOURCE_DIR / f"{tool_id}.json", id=f"{tool_id}-json"),
    ]


def _assert_boolean_form(built):
    inputs = {parameter["name"]: parameter for parameter in built["inputs"]}
    for name, value in BOOLEAN_DEFAULTS.items():
        assert inputs[name]["value"] is value
        assert inputs[name]["optional"] is name.startswith("optional_")


def _assert_boolean_jobs(tool, tool_input_format):
    tool.execute().with_inputs(tool_input_format.when.any({})).assert_has_single_job.with_output("output").with_json(
        BOOLEAN_DEFAULTS
    )
    tool.execute().with_inputs(tool_input_format.when.any(BOOLEAN_OVERRIDES)).assert_has_single_job.with_output(
        "output"
    ).with_json(BOOLEAN_OVERRIDES)


@pytest.mark.parametrize("user_tool", _sources("gx_user_boolean_defaults"), indirect=True)
def test_user_boolean_contract(user_tool: DescribeUserTool, tool_input_format: DescribeToolInputs):
    _assert_boolean_form(user_tool.build())
    _assert_boolean_jobs(user_tool, tool_input_format)


@requires_tool_id("gx_user_boolean_defaults")
def test_disk_boolean_contract(
    required_tool: RequiredTool,
    dataset_populator: DatasetPopulator,
    history_id: str,
    tool_input_format: DescribeToolInputs,
):
    _assert_boolean_form(dataset_populator.build_tool_state("gx_user_boolean_defaults", history_id))
    _assert_boolean_jobs(required_tool, tool_input_format)


def _assert_conditional_form(built):
    conditional = built["inputs"][0]
    assert conditional["name"] == "choice"
    assert conditional["test_param"]["value"] is True
    assert conditional["test_param"]["optional"] is False
    assert [case["value"] for case in conditional["cases"]] == ["true", "false"]


def _assert_conditional_jobs(tool, tool_input_format):
    tool.execute().with_inputs(tool_input_format.when.any({})).assert_has_single_job.with_output("output").with_json(
        {"choice": {"flag": True, "yes": "true branch"}}
    )
    inputs = tool_input_format.when.flat({"choice|flag": False, "choice|no": "chosen"}).when.nested(
        {"choice": {"flag": False, "no": "chosen"}}
    )
    tool.execute().with_inputs(inputs).assert_has_single_job.with_output("output").with_json(
        {"choice": {"flag": False, "no": "chosen"}}
    )


@pytest.mark.parametrize("user_tool", _sources("gx_user_boolean_conditional"), indirect=True)
def test_user_conditional_contract(user_tool: DescribeUserTool, tool_input_format: DescribeToolInputs):
    _assert_conditional_form(user_tool.build())
    _assert_conditional_jobs(user_tool, tool_input_format)


@requires_tool_id("gx_user_boolean_conditional")
def test_disk_conditional_contract(
    required_tool: RequiredTool,
    dataset_populator: DatasetPopulator,
    history_id: str,
    tool_input_format: DescribeToolInputs,
):
    _assert_conditional_form(dataset_populator.build_tool_state("gx_user_boolean_conditional", history_id))
    _assert_conditional_jobs(required_tool, tool_input_format)


class UnsupportedStructuralInput(Exception):
    pass


@pytest.mark.parametrize(
    "user_tool", _sources("gx_user_repeat", SOURCE_DIR) + _sources("gx_user_section", SOURCE_DIR), indirect=True
)
@pytest.mark.xfail(strict=True, raises=UnsupportedStructuralInput, reason="#23888: canonical groups fail API parsing")
def test_user_structural_contract(user_tool: DescribeUserTool):
    response = user_tool.build_raw()
    if response.status_code == 500:
        raise UnsupportedStructuralInput(response.text)
    assert response.status_code == 200, response.text
    assert response.json()["inputs"][0]["name"] == "group"


@requires_tool_id("gx_user_boolean_checked")
def test_disk_checked_compatibility(
    required_tool: RequiredTool,
    dataset_populator: DatasetPopulator,
    history_id: str,
    tool_input_format: DescribeToolInputs,
):
    built = dataset_populator.build_tool_state("gx_user_boolean_checked", history_id)
    assert built["inputs"][0]["value"] is True
    assert built["inputs"][1]["value"] is False
    required_tool.execute().with_inputs(tool_input_format.when.any({})).assert_has_single_job.with_output(
        "output"
    ).with_json({"flag": True, "precedence": False})


@pytest.mark.parametrize(
    "user_tool", [TOOL_DIR / "parameters" / "legacy" / "gx_user_boolean_checked.yml"], indirect=True
)
def test_user_checked_is_rejected(user_tool: DescribeUserTool):
    for response in (user_tool.build_raw(), user_tool.create_raw(), user_tool.runtime_model_raw()):
        assert response.status_code == 400, response.text
        assert "checked" in response.text
        assert "Extra inputs are not permitted" in response.text


@pytest.mark.parametrize(
    "user_tool, value",
    [
        (SOURCE_DIR / "configfile_user_defined.json", "hello!"),
        (SOURCE_DIR / "gx_select_multiple_one_default_user.json", "--ex3"),
    ],
    indirect=["user_tool"],
)
def test_user_omitted_optionality(user_tool: DescribeUserTool, value):
    parameter = user_tool.build()["inputs"][0]
    assert parameter["value"] == value
    assert parameter["optional"] is False


@pytest.mark.parametrize(
    "tool_id, value",
    [
        pytest.param("configfile", "hello!", marks=pytest.mark.requires_tool_id("configfile")),
        pytest.param(
            "gx_select_multiple_one_default_user",
            "--ex3",
            marks=pytest.mark.requires_tool_id("gx_select_multiple_one_default_user"),
        ),
    ],
)
@pytest.mark.xfail(
    strict=True,
    raises=InferredOptionality,
    reason="#23888: disk YAML infers XML optionality for omitted optional=False",
)
def test_disk_omitted_optionality(dataset_populator: DatasetPopulator, history_id: str, tool_id: str, value):
    parameter = dataset_populator.build_tool_state(tool_id, history_id)["inputs"][0]
    assert parameter["value"] == value
    if parameter["optional"] is True:
        raise InferredOptionality("Disk YAML infers optional=True instead of canonical False")
    assert parameter["optional"] is False


@pytest.mark.parametrize("user_tool", _sources("gx_user_boolean_optional_omitted"), indirect=True)
def test_user_optional_boolean_omitted(user_tool: DescribeUserTool, tool_input_format: DescribeToolInputs):
    parameter = user_tool.build()["inputs"][0]
    assert parameter["value"] is False
    assert parameter["optional"] is True
    user_tool.execute().with_inputs(tool_input_format.when.any({})).assert_has_single_job.with_output(
        "output"
    ).with_json({"flag": False})
    user_tool.execute().with_inputs(tool_input_format.when.any({"flag": None})).assert_has_single_job.with_output(
        "output"
    ).with_json({"flag": None})


@requires_tool_id("gx_user_boolean_optional_omitted")
@pytest.mark.xfail(
    strict=True,
    raises=MissingOptionalBooleanDefault,
    reason="#23888: disk YAML loses canonical optional Boolean False default",
)
def test_disk_optional_boolean_omitted(dataset_populator: DatasetPopulator, history_id: str):
    parameter = dataset_populator.build_tool_state("gx_user_boolean_optional_omitted", history_id)["inputs"][0]
    assert parameter["optional"] is True
    if parameter["value"] is None:
        raise MissingOptionalBooleanDefault("Disk YAML supplies None instead of canonical False")
    assert parameter["value"] is False


@pytest.mark.parametrize("user_tool", _sources("gx_user_boolean_optional_null"), indirect=True)
@pytest.mark.parametrize(
    "tool_input_format",
    [
        "legacy",
        "21.01",
        pytest.param(
            "request",
            marks=pytest.mark.xfail(
                strict=True,
                raises=RequestNullBooleanDefault,
                reason="#23888: request execution changes omitted null Boolean default to False",
            ),
        ),
    ],
    indirect=True,
)
def test_user_optional_boolean_null(user_tool: DescribeUserTool, tool_input_format: DescribeToolInputs):
    parameter = user_tool.build()["inputs"][0]
    assert parameter["value"] is None
    assert parameter["optional"] is True
    _assert_null_boolean_job(user_tool, tool_input_format)


@requires_tool_id("gx_user_boolean_optional_null")
@pytest.mark.parametrize(
    "tool_input_format",
    [
        "legacy",
        "21.01",
        pytest.param(
            "request",
            marks=pytest.mark.xfail(
                strict=True,
                raises=RequestNullBooleanDefault,
                reason="#23888: request execution changes omitted null Boolean default to False",
            ),
        ),
    ],
    indirect=True,
)
def test_disk_optional_boolean_null(
    required_tool: RequiredTool,
    dataset_populator: DatasetPopulator,
    history_id: str,
    tool_input_format: DescribeToolInputs,
):
    parameter = dataset_populator.build_tool_state("gx_user_boolean_optional_null", history_id)["inputs"][0]
    assert parameter["value"] is None
    assert parameter["optional"] is True
    _assert_null_boolean_job(required_tool, tool_input_format)


def _assert_null_boolean_job(tool, tool_input_format):
    output = tool.execute().with_inputs(tool_input_format.when.any({})).assert_has_single_job.with_output("output")
    actual = output.json
    if tool_input_format.is_request and set(actual) == {"flag"} and actual["flag"] is False:
        raise RequestNullBooleanDefault("Request execution supplies False instead of the declared null default")
    output.with_json({"flag": None})
