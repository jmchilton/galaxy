"""Check ``tool_panel`` selectors in ``navigation.yml`` against links shaped like the tool panel's."""

import pytest

from galaxy.navigation.data import load_root_component
from galaxy.selenium.smart_components import SmartComponent
from .test_has_driver import (
    TestHasDriverImpl,
    TestHasPlaywrightDriverImpl,
)

TOOL_SHED_GUID = "toolshed.g2.bx.psu.edu/repos/iuc/umi_tools_extract/umi_tools_extract/1.1.2+galaxy2"


@pytest.fixture(params=["selenium", "playwright"])
def has_driver_instance(request, driver, playwright_resources, base_url):
    if request.param == "selenium":
        return TestHasDriverImpl(driver)
    else:
        return TestHasPlaywrightDriverImpl(playwright_resources)


@pytest.fixture
def tool_panel(has_driver_instance, base_url):
    has_driver_instance.navigate_to(f"{base_url}/tool_panel.html")
    return SmartComponent(load_root_component(), has_driver_instance).tool_panel


@pytest.mark.parametrize("tool_id", ["cat1", TOOL_SHED_GUID])
def test_tool_link_finds_tool_by_id(tool_panel, tool_id):
    links = tool_panel.tool_link(tool_id=tool_id).all()
    assert [link.get_attribute("data-tool-id") for link in links] == [tool_id]


@pytest.mark.parametrize("tool_id", ["cat1", TOOL_SHED_GUID])
def test_outer_tool_link_finds_tool_by_id(tool_panel, tool_id):
    links = tool_panel.outer_tool_link(tool_id=tool_id).all()
    assert [link.get_attribute("data-tool-id") for link in links] == [tool_id]


def test_tool_link_skips_disabled_and_data_source_tools(tool_panel):
    assert tool_panel.tool_link(tool_id="disabled_tool").all() == []
    assert tool_panel.tool_link(tool_id="ucsc_table_direct1").all() == []


def test_data_source_tool_link_finds_data_source_tool(tool_panel):
    links = tool_panel.data_source_tool_link(tool_id="ucsc_table_direct1").all()
    assert [link.get_attribute("data-tool-id") for link in links] == ["ucsc_table_direct1"]
