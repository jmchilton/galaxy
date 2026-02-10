"""Tests for custom tool creation and management."""

import platform

from .framework import (
    selenium_test,
    SeleniumTestCase,
)


class TestCustomTools(SeleniumTestCase):
    ensure_registered = True

    def assert_baseline_accessibility(self):
        """Skip accessibility checks for custom tools tests due to Monaco editor issues."""
        pass

    @selenium_test
    def test_create_custom_tool(self):
        """Test creating a new custom tool through the UI."""
        with self.dataset_populator.user_tool_execute_permissions():
            tool_uuid = self.create_new_custom_tool()
            assert tool_uuid, "Tool UUID should be returned after saving."
            self.components.custom_tools.tool_link(tool_uuid=tool_uuid).wait_for_clickable()

    @selenium_test
    def test_run_custom_tool(self):
        test_path = self.get_filename("1.fasta")
        self.perform_upload(test_path, on_current_page=True)
        self.history_panel_wait_for_hid_ok(1)
        with self.dataset_populator.user_tool_execute_permissions():
            tool_uuid = self.create_new_custom_tool()
            assert tool_uuid, "Tool UUID should be returned after saving."
            self.components.custom_tools.tool_link(tool_uuid=tool_uuid).wait_for_and_click()
            self.sleep_for(self.wait_types.UX_RENDER)
            self.components.tool_form.execute.wait_for_and_click()
            self.history_panel_wait_for_hid_ok(2)
            self.hda_click_primary_action_button(2, "rerun")
            self.components.tool_form.execute.wait_for_and_click()
            self.history_panel_wait_for_hid_ok(3)

    def create_new_custom_tool(self) -> str:
        self.home()
        self.open_tool_editor()
        self.paste_tool()
        return self.save_tool()

    def open_tool_editor(self):
        # Navigate via Custom Tools activity panel
        self.components.custom_tools.activity.wait_for_and_click()
        # Use the component selector for the create button
        self.components.custom_tools.create_button.wait_for_and_click()
        # Wait for the Tool Editor heading to appear
        self.wait_for_selector_visible("h1")
        self.wait_for_selector_visible(".monaco-editor")

    def save_tool(self) -> str:
        self.components.custom_tools.save_button.wait_for_and_click()
        # Wait for save operation to complete
        self.sleep_for(self.wait_types.UX_TRANSITION)
        # Verify save was successful
        return self.current_url.split("/tools/editor/")[1]

    def paste_tool(self):
        tool_yaml = """class: GalaxyUserTool
id: test_cat_tool
name: Test Cat Tool
version: "0.1"
description: Concatenate test files
container: busybox
shell_command: |
  cat $(inputs.datasets.map((input) => input.path).join(' ')) > output.txt

inputs:
- name: datasets
  multiple: true
  type: data

outputs:
- name: output1
  type: data
  format_source: datasets
  from_work_dir: output.txt
"""
        # Wait for Monaco editor to initialize
        self.sleep_for(self.wait_types.UX_RENDER)
        editor_container = self.wait_for_selector_visible(".monaco-editor")
        editor_container.click()
        self.sleep_for(self.wait_types.UX_RENDER)

        # Select all and delete existing content
        modifier = "Meta" if platform.system() == "Darwin" else "Control"
        self.keyboard_combo(modifier, "a")
        self.keyboard_press("Delete")

        # Type new tool YAML
        self.keyboard_type(tool_yaml)
