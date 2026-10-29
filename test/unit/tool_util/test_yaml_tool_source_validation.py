from typing import (
    Any,
    Dict,
)

import pytest
from pydantic import ValidationError

from galaxy.tool_util.parser.yaml import YamlToolSource

VALID_TOOL: Dict[str, Any] = {
    "class": "GalaxyTool",
    "id": "legacy_dialect",
    "name": "Legacy dialect",
    "version": "1.0",
    "shell_command": "echo hi > out.txt",
    "inputs": [],
    "outputs": [{"name": "out", "type": "data", "format": "txt", "from_work_dir": "out.txt"}],
}

CONDITIONAL_TEST_PARAMETER = {"name": "use", "type": "boolean"}

LEGACY_DIALECT = {
    "cheetah_command": {"shell_command": None, "command": "echo hi > $out"},
    "base_command": {"shell_command": None, "base_command": "echo", "arguments": ["hi"]},
    "runtime_version": {"runtime_version": {"command": "echo --version"}},
    "numeric_version": {"version": 1.0},
    "package_requirement": {"requirements": [{"type": "package", "name": "bwa", "version": "1.0"}]},
    "boolean_checked": {"inputs": [{"name": "flag", "type": "boolean", "checked": True}]},
    "repeat_blocks": {"inputs": [{"name": "rep", "type": "repeat", "blocks": [{"name": "n", "type": "integer"}]}]},
    "conditional_when": {
        "inputs": [
            {
                "name": "cond",
                "type": "conditional",
                "test_parameter": CONDITIONAL_TEST_PARAMETER,
                "when": {True: [{"name": "n", "type": "integer"}], False: []},
            }
        ]
    },
    "select_display": {
        "inputs": [{"name": "sel", "type": "select", "display": "radio", "options": [{"value": "a", "label": "A"}]}]
    },
    "untyped_output": {"outputs": [{"name": "out", "format": "txt", "from_work_dir": "out.txt"}]},
    "static_collection_elements": {
        "outputs": [
            {
                "name": "pair",
                "type": "collection",
                "collection_type": "paired",
                "elements": {"forward": {"from_work_dir": "f.txt"}, "reverse": {"from_work_dir": "r.txt"}},
            }
        ]
    },
}


def _tool(tool_class: str, overrides: Dict[str, Any]) -> Dict[str, Any]:
    tool = {**VALID_TOOL, "class": tool_class, **overrides}
    if tool_class == "GalaxyUserTool":
        tool["container"] = "busybox"
    return {key: value for key, value in tool.items() if value is not None}


@pytest.mark.parametrize("tool_class", ["GalaxyTool", "GalaxyUserTool"])
def test_canonical_tool_loads(tool_class: str):
    tool_source = YamlToolSource(_tool(tool_class, {}))
    assert tool_source.parse_shell_command() == "echo hi > out.txt"


# Location of the error each legacy spelling must raise.
LEGACY_ERROR_LOCATIONS = {
    "cheetah_command": ("command",),
    "base_command": ("base_command",),
    "runtime_version": ("runtime_version",),
    "numeric_version": ("version",),
    "package_requirement": ("requirements", 0),
    "boolean_checked": ("inputs", 0, "boolean", "checked"),
    "repeat_blocks": ("inputs", 0, "repeat", "blocks"),
    "conditional_when": ("inputs", 0, "conditional", "when"),
    "select_display": ("inputs", 0, "select", "display"),
    "untyped_output": ("outputs", 0),
    "static_collection_elements": ("outputs", 0, "collection", "elements"),
}


@pytest.mark.parametrize("case", LEGACY_DIALECT.keys())
def test_galaxy_tool_rejects_legacy_dialect(case: str):
    with pytest.raises(ValidationError) as exc_info:
        YamlToolSource(_tool("GalaxyTool", LEGACY_DIALECT[case]))
    location = LEGACY_ERROR_LOCATIONS[case]
    error_locations = [error["loc"][: len(location)] for error in exc_info.value.errors()]
    assert location in error_locations


def test_classless_tool_keeps_legacy_dialect():
    tool = _tool("GalaxyTool", LEGACY_DIALECT["cheetah_command"])
    del tool["class"]
    assert YamlToolSource(tool).parse_command() == "echo hi > $out"


def test_validation_leaves_mapping_outputs_in_place():
    tool = _tool("GalaxyTool", {"outputs": {"out": {"type": "data", "format": "txt", "from_work_dir": "out.txt"}}})
    tool_source = YamlToolSource(tool)
    assert tool_source.root_dict["outputs"] == {"out": {"type": "data", "format": "txt", "from_work_dir": "out.txt"}}
    outputs, _ = tool_source.parse_outputs(None)
    assert list(outputs) == ["out"]
