from galaxy.tool_util.model_factory import (
    parse_tool,
)
from galaxy.tool_util.parser.factory import get_tool_source
from galaxy.tool_util.unittest_utils import functional_test_tool_path

# Field-level parse assertions (requirements, containers, stdio) live in the
# declarative suite: test/unit/tool_util/tool_parsing/expectations/. This file
# retains only checks the path-navigation harness cannot express -- currently
# pydantic serialization round-tripping.


def tool_source_for(tool_name: str):
    return get_tool_source(functional_test_tool_path(tool_name))


def parsed_tool_for(tool_name: str):
    return parse_tool(tool_source_for(tool_name))


def test_parsed_tool_serializes():
    tool_source = tool_source_for("mulled_example_explicit.xml")

    parsed_tool = parse_tool(tool_source)

    assert parsed_tool.model_dump(mode="json")["requirements"][0]["name"] == "bwa"
    assert parsed_tool.model_dump(mode="json")["containers"][0]["type"] == "docker"
    assert parsed_tool.model_dump_json()
