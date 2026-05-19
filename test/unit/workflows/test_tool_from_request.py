from types import SimpleNamespace
from unittest.mock import Mock

from galaxy.app_unittest_utils.tools_support import mock_app_for_tool_support
from galaxy.workflow import extract

CAT_XML = """<tool id="cat" name="cat" version="1.0">
    <command>cat $input1 > $output1</command>
    <inputs><param name="input1" type="data" /></inputs>
    <outputs><data name="output1" /></outputs>
</tool>"""


def _trans():
    return SimpleNamespace(app=mock_app_for_tool_support())


def test_tool_from_request_recovers_guid_from_tool_source():
    # Toolshed/installed-tool identity must round-trip through the persisted
    # ToolSource.tool_id so the reconstructed Tool.id equals the namespaced
    # guid (not the short XML id), letting the extracted step resolve.
    guid = "toolshed.example/repos/o/r/cat/1.0"
    tool_source = SimpleNamespace(
        source=CAT_XML,
        source_class="XmlToolSource",
        tool_id=guid,
        dynamic_tool=None,
    )
    tool_request = SimpleNamespace(tool_source=tool_source)

    tool = extract._tool_from_request(_trans(), tool_request)

    assert tool.id == guid


def test_tool_from_request_attaches_dynamic_tool_from_tool_source():
    # User/dynamic-tool identity must round-trip through the persisted
    # ToolSource.dynamic_tool FK so the extracted step can resolve via
    # tool_uuid (WorkflowStep.tool_uuid = dynamic_tool.uuid).
    dynamic_tool_mock = Mock(spec_set=["id", "uuid"])
    dynamic_tool_mock.id = 42
    dynamic_tool_mock.uuid = "00000000-0000-0000-0000-000000000042"
    tool_source = SimpleNamespace(
        source=CAT_XML,
        source_class="XmlToolSource",
        tool_id=None,
        dynamic_tool=dynamic_tool_mock,
    )
    tool_request = SimpleNamespace(tool_source=tool_source)

    tool = extract._tool_from_request(_trans(), tool_request)

    assert tool.dynamic_tool is dynamic_tool_mock


def test_tool_from_request_no_identity_falls_back_to_short_id():
    # Legacy rows (NULL tool_id, no DynamicTool) keep today's behavior:
    # Tool.id is the short XML id and Tool.dynamic_tool stays None.
    tool_source = SimpleNamespace(
        source=CAT_XML,
        source_class="XmlToolSource",
        tool_id=None,
        dynamic_tool=None,
    )
    tool_request = SimpleNamespace(tool_source=tool_source)

    tool = extract._tool_from_request(_trans(), tool_request)

    assert tool.id == "cat"
    assert tool.dynamic_tool is None
