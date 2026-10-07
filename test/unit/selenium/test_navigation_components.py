"""Check the public structure ``galaxy.navigation`` components expose for browsing the tree."""

from galaxy.navigation.data import load_root_component


def test_sub_components_lists_children():
    root = load_root_component()
    assert "workflow_extract" in root.sub_components
    assert root.sub_components.tool_panel is root.tool_panel


def test_selectors_and_labels_are_public():
    tool_panel = load_root_component().tool_panel
    assert "tool_link" in tool_panel.selectors
    assert "tool_link" not in tool_panel.sub_components
