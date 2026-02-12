from .framework import (
    managed_history,
    retry_assertion_during_transitions,
    selenium_test,
    SeleniumTestCase,
)


class TestHistoryNotebooks(SeleniumTestCase):
    ensure_registered = True

    @selenium_test
    @managed_history
    def test_navigate_to_notebooks_via_history_menu(self):
        """Navigate to notebooks via history panel options menu."""
        self.navigate_to_history_notebooks_via_menu()
        self.screenshot("history_notebooks_list_empty")
        self.components.history_notebooks.empty_state.wait_for_visible()

    @selenium_test
    @managed_history
    def test_create_notebook(self):
        """Create a new notebook and verify editor appears."""
        self.navigate_to_history_notebooks_via_menu()
        self.history_notebook_create(screenshot_name="history_notebook_create")
        self.components.history_notebooks.editor.wait_for_visible()
        title_text = self.components.history_notebooks.toolbar_title.wait_for_text()
        assert "Untitled" in title_text or title_text != ""
        self.screenshot("history_notebook_editor_new")

    @selenium_test
    @managed_history
    def test_notebook_empty_history(self):
        """Create notebook for an empty history."""
        self.navigate_to_history_notebooks_via_menu()
        self.history_notebook_create()
        self.components.history_notebooks.editor.wait_for_visible()

        self.history_notebook_editor_set_content("# Empty History Notes\n\nNo datasets yet.")
        self.history_notebook_save()

        self.history_notebook_go_back()
        self.history_notebook_assert_item_count(1)
        self.screenshot("history_notebook_empty_history")

    @selenium_test
    @managed_history
    def test_edit_and_save_notebook(self):
        """Edit notebook content, save, reload, verify persistence."""
        self.navigate_to_history_notebooks_via_menu()
        self.history_notebook_create()

        test_content = "# My Analysis\n\nThis is a test notebook."
        self.history_notebook_editor_set_content(test_content)

        self.components.history_notebooks.unsaved_indicator.wait_for_visible()
        self.screenshot("history_notebook_unsaved")

        self.history_notebook_save()
        self.screenshot("history_notebook_saved")

        self.history_notebook_go_back()
        self.history_notebook_assert_item_count(1)

        self.components.history_notebooks.notebook_item.wait_for_and_click()
        self.components.history_notebooks.editor.wait_for_visible()

        editor = self.components.history_notebooks.markdown_editor
        content = editor.wait_for_value()
        assert "My Analysis" in content
        self.screenshot("history_notebook_reloaded")

    @selenium_test
    @managed_history
    def test_notebook_save_button_disabled_when_clean(self):
        """Verify save button is disabled when no changes exist."""
        self.navigate_to_history_notebooks_via_menu()
        self.history_notebook_create()
        self.components.history_notebooks.editor.wait_for_visible()

        save_button = self.components.history_notebooks.save_button
        save_button.assert_disabled()

        self.components.history_notebooks.unsaved_indicator.assert_absent_or_hidden()

        self.history_notebook_editor_set_content("some content")

        @retry_assertion_during_transitions
        def assert_save_enabled():
            assert not save_button.has_class("disabled")

        assert_save_enabled()

        self.history_notebook_save()

        @retry_assertion_during_transitions
        def assert_save_disabled_again():
            save_button.assert_disabled()

        assert_save_disabled_again()
        self.screenshot("history_notebook_save_disabled")

    @selenium_test
    @managed_history
    def test_multiple_notebooks_per_history(self):
        """Create multiple notebooks for the same history."""
        history_id = self.current_history_id()
        self.dataset_populator.new_history_notebook(history_id, title="First Notebook", content="# First")
        self.dataset_populator.new_history_notebook(history_id, title="Second Notebook", content="# Second")

        self.navigate_to_history_notebooks_via_menu()
        self.screenshot("history_notebooks_list_multiple")

        self.history_notebook_assert_item_count(2)

    @selenium_test
    @managed_history
    def test_notebook_with_dataset_hid_reference(self):
        """Create notebook with HID reference via API, verify content."""
        history_id = self.current_history_id()
        self.perform_upload(self.get_filename("1.fasta"))
        self.history_panel_wait_for_hid_ok(1)

        content = "# Analysis\n\n```galaxy\nhistory_dataset_display(hid=1)\n```\n"
        self.dataset_populator.new_history_notebook(history_id, title="HID Test", content=content)

        # Navigate via menu and click the notebook item
        self.navigate_to_history_notebooks_via_menu()
        self.history_notebook_assert_item_count(1)
        self.components.history_notebooks.notebook_item.wait_for_and_click()
        self.components.history_notebooks.editor.wait_for_visible()
        self.screenshot("history_notebook_hid_content")

        # Content is resolved by rewrite_content_for_export: hid=1 becomes
        # history_dataset_id=<encoded_id> for rendering.
        editor = self.components.history_notebooks.markdown_editor
        value = editor.wait_for_value()
        assert "history_dataset_display" in value
        assert "history_dataset_id=" in value

    @selenium_test
    @managed_history
    def test_toolbox_visible_in_notebook_mode(self):
        """Verify toolbox renders with dataset entries in notebook mode."""
        self.perform_upload(self.get_filename("1.fasta"))
        self.history_panel_wait_for_hid_ok(1)

        self.navigate_to_history_notebooks_via_menu()
        self.history_notebook_create()
        self.components.history_notebooks.editor.wait_for_visible()

        # Verify the toolbox "Display Dataset" entry exists (notebook mode)
        embed_dataset = self.wait_for_selector_visible('.toolTitle .title-link[data-tool-id="history_dataset_display"]')
        assert embed_dataset is not None
        self.screenshot("history_notebook_toolbox_visible")

        # Click it and verify the DataDialog opens
        embed_dataset = self.wait_for_selector_clickable(
            '.toolTitle .title-link[data-tool-id="history_dataset_display"]'
        )
        embed_dataset.click()
        self.sleep_for(self.wait_types.UX_RENDER)
        dialog = self.wait_for_selector_visible(".selection-dialog-modal")
        assert dialog is not None
        self.screenshot("history_notebook_toolbox_dataset_dialog")

    @selenium_test
    @managed_history
    def test_delete_notebook(self):
        """Delete a notebook via API and verify it disappears from list."""
        history_id = self.current_history_id()

        self.dataset_populator.new_history_notebook(history_id, title="Keep This")
        nb2 = self.dataset_populator.new_history_notebook(history_id, title="Delete This")

        self.navigate_to_history_notebooks_via_menu()
        self.history_notebook_assert_item_count(2)

        # Delete via API, then go home and navigate back via menu
        self.dataset_populator.delete_history_notebook(history_id, nb2["id"])
        self.home()
        self.navigate_to_history_notebooks_via_menu()

        @retry_assertion_during_transitions
        def assert_one_notebook():
            items = self.components.history_notebooks.notebook_item.all()
            assert len(items) == 1

        assert_one_notebook()
        self.screenshot("history_notebook_after_delete")

    @selenium_test
    @managed_history
    def test_notebook_permissions_shared_history(self):
        """Verify notebooks visible on shared history -- publish and check API."""
        history_id = self.current_history_id()

        notebook = self.dataset_populator.new_history_notebook(
            history_id, title="Shared Notebook", content="# Shared Content"
        )

        # Publish the history via UI
        self.current_history_publish()

        # Verify the notebook is still accessible via API after publishing
        fetched = self.dataset_populator.get_history_notebook(history_id, notebook["id"])
        assert fetched["title"] == "Shared Notebook"
        self.screenshot("history_notebook_shared_view")
