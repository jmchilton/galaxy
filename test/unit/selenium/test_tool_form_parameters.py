"""Flattening a tool's build model into the parameter paths tool_form_fill takes."""

from galaxy.selenium.navigates_galaxy import (
    tool_form_parameters_from_build,
    ToolFormParameter,
)

HDA = {"id": "e89067bb68bee7a0", "hid": 1, "name": "Pasted Dataset 1", "src": "hda"}
DATA_OPTIONS = {"dce": [], "ldda": [], "hda": [HDA], "hdca": []}


def _data(name, label):
    return {
        "name": name,
        "type": "data",
        "label": label,
        "value": {"values": [{"id": HDA["id"], "src": "hda"}]},
        "optional": False,
        "options": DATA_OPTIONS,
    }


def test_data_and_repeat_paths():
    inputs = [
        _data("input1", "Concatenate Dataset"),
        {
            "name": "queries",
            "type": "repeat",
            "title": "Dataset",
            "min": 0,
            "max": None,
            "inputs": [_data("input2", "Select")],
            "cache": [],
        },
    ]
    assert tool_form_parameters_from_build(inputs) == [
        ToolFormParameter(
            "input1", "Concatenate Dataset", "data", "1: Pasted Dataset 1", [("1: Pasted Dataset 1", "1")]
        ),
        ToolFormParameter("queries", "Dataset", "repeat", 0, []),
        ToolFormParameter("queries_0|input2", "Select", "data", "1: Pasted Dataset 1", [("1: Pasted Dataset 1", "1")]),
    ]


def test_conditional_lists_every_case_with_its_condition():
    inputs = [
        {
            "name": "conditional_parameter",
            "type": "conditional",
            "test_param": {
                "name": "test_parameter",
                "type": "select",
                "label": "",
                "value": "a",
                "options": [["A", "a", False], ["B", "b", False]],
            },
            "cases": [
                {"value": "a", "inputs": [{"name": "integer_parameter", "type": "integer", "label": "", "value": "1"}]},
                {
                    "value": "b",
                    "inputs": [{"name": "boolean_parameter", "type": "boolean", "label": "Flag", "value": False}],
                },
            ],
        }
    ]
    assert tool_form_parameters_from_build(inputs) == [
        ToolFormParameter(
            "conditional_parameter|test_parameter", "test_parameter", "select", "a", [("A", "a"), ("B", "b")]
        ),
        ToolFormParameter(
            "conditional_parameter|integer_parameter",
            "integer_parameter",
            "integer",
            "1",
            [],
            "conditional_parameter|test_parameter=a",
        ),
        ToolFormParameter(
            "conditional_parameter|boolean_parameter",
            "Flag",
            "boolean",
            False,
            [],
            "conditional_parameter|test_parameter=b",
        ),
    ]


def test_section_and_repeat_instances_use_form_prefixes():
    inputs = [
        {
            "name": "parameter",
            "type": "section",
            "title": "Options",
            "inputs": [{"name": "flag", "type": "boolean", "label": "", "value": True}],
        },
        {
            "name": "the_repeat",
            "type": "repeat",
            "title": "Repeat",
            "inputs": [{"name": "texttest", "type": "text", "label": "", "value": ""}],
            "cache": [
                [{"name": "texttest", "type": "text", "label": "", "value": "one"}],
                [{"name": "texttest", "type": "text", "label": "", "value": "two"}],
            ],
        },
    ]
    assert [(p.path, p.value) for p in tool_form_parameters_from_build(inputs)] == [
        ("parameter|flag", True),
        ("the_repeat", 2),
        ("the_repeat_0|texttest", "one"),
        ("the_repeat_1|texttest", "two"),
    ]
