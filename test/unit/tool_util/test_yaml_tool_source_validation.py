from typing import (
    Any,
    Dict,
)

import pytest

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


def _tool(tool_class: str, overrides: Dict[str, Any]) -> Dict[str, Any]:
    tool = {**VALID_TOOL, "class": tool_class, **overrides}
    if tool_class == "GalaxyUserTool":
        tool["container"] = "busybox"
    return {key: value for key, value in tool.items() if value is not None}


@pytest.mark.parametrize("tool_class", ["GalaxyTool", "GalaxyUserTool"])
def test_canonical_tool_loads(tool_class: str):
    tool_source = YamlToolSource(_tool(tool_class, {}))
    assert tool_source.parse_shell_command() == "echo hi > out.txt"


def test_classless_tool_keeps_legacy_dialect():
    tool = _tool("GalaxyTool", {"shell_command": None, "command": "echo hi > $out"})
    del tool["class"]
    assert YamlToolSource(tool).parse_command() == "echo hi > $out"


def test_validation_leaves_mapping_outputs_in_place():
    tool = _tool("GalaxyTool", {"outputs": {"out": {"type": "data", "format": "txt", "from_work_dir": "out.txt"}}})
    tool_source = YamlToolSource(tool)
    assert tool_source.root_dict["outputs"] == {"out": {"type": "data", "format": "txt", "from_work_dir": "out.txt"}}
    outputs, _ = tool_source.parse_outputs(None)
    assert list(outputs) == ["out"]
