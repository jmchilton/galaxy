"""Check the public structure ``galaxy.navigation`` components expose for browsing the tree."""

from galaxy.navigation.components import Target
from galaxy.navigation.data import load_root_component
from galaxy.selenium.smart_components import (
    SmartComponent,
    SmartTarget,
)


def test_sub_components_lists_children():
    root = load_root_component()
    assert "workflow_extract" in root.sub_components
    assert root.sub_components.tool_panel is root.tool_panel


def test_selectors_and_labels_are_public():
    tool_panel = load_root_component().tool_panel
    assert "tool_link" in tool_panel.selectors
    assert "tool_link" not in tool_panel.sub_components


def test_resolve_component_returns_target_for_path():
    root = load_root_component()
    target = root.resolve_component("history_panel.item(hid=3).title")
    assert isinstance(target, Target)
    assert target.component_locator == root.resolve_component_locator("history_panel.item(hid=3).title")


def test_resolve_component_without_path_returns_base_selector():
    tool_panel = load_root_component().tool_panel
    assert tool_panel.tool_link(tool_id="cat1").resolve_component() is not None
    assert load_root_component().workflow_extract.resolve_component().component_locator.locator == (
        '[data-description="workflow-extraction-form"]'
    )


def test_smart_component_resolve_component_wraps_target():
    smart = SmartComponent(load_root_component(), has_driver=None)
    target = smart.resolve_component("tool_panel.tool_link(tool_id=cat1)")
    assert isinstance(target, SmartTarget)
    assert target.component_locator.locator.startswith("a.tool-link")
