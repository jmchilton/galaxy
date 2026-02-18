from .framework import (
    managed_history,
    retry_assertion_during_transitions,
    selenium_only,
    selenium_test,
    SeleniumTestCase,
)


class TestHistoryNotebooks(SeleniumTestCase):
    ensure_registered = True

    @selenium_test
    @managed_history
    def test_navigate_to_notebooks(self):
        """Navigate to notebooks via direct URL."""
        self.navigate_to_history_notebooks()
        self.screenshot("history_notebooks_list_empty")
        self.components.history_notebooks.empty_state.wait_for_visible()

    @selenium_test
    @managed_history
    def test_navigate_via_notebook_icon(self):
        """Click notebook icon in history counter bar opens notebook editor.

        When no notebooks exist, resolveCurrentNotebook auto-creates one.
        """
        self.navigate_to_current_notebook()
        self.components.history_notebooks.editor.wait_for_visible()
        self.screenshot("history_notebook_icon_auto_create")

    @selenium_test
    @managed_history
    def test_notebook_icon_opens_existing(self):
        """Click notebook icon navigates to existing notebook."""
        history_id = self.current_history_id()
        self.dataset_populator.new_history_notebook(history_id, title="Existing", content="# Hello")

        self.navigate_to_current_notebook()
        self.components.history_notebooks.editor.wait_for_visible()
        editor = self.components.history_notebooks.markdown_editor
        assert "Hello" in editor.wait_for_value()
        self.screenshot("history_notebook_icon_existing")

    @selenium_test
    @managed_history
    def test_create_notebook(self):
        """Create a new notebook and verify editor appears."""
        self.navigate_to_history_notebooks()
        self.history_notebook_create(screenshot_name="history_notebook_create")
        self.components.history_notebooks.editor.wait_for_visible()
        title_text = self.components.history_notebooks.toolbar_title.wait_for_text()
        assert "Untitled" in title_text or title_text != ""
        self.screenshot("history_notebook_editor_new")

    @selenium_test
    @managed_history
    def test_notebook_empty_history(self):
        """Create notebook for an empty history."""
        self.navigate_to_history_notebooks()
        self.history_notebook_create()
        self.components.history_notebooks.editor.wait_for_visible()

        self.history_notebook_editor_set_content("# Empty History Notes\n\nNo datasets yet.")
        self.history_notebook_save()

        self.history_notebook_manage()
        self.history_notebook_assert_item_count(1)
        self.screenshot("history_notebook_empty_history")

    @selenium_test
    @managed_history
    def test_edit_and_save_notebook(self):
        """Edit notebook content, save, reload, verify persistence."""
        self.navigate_to_history_notebooks()
        self.history_notebook_create()

        test_content = "# My Analysis\n\nThis is a test notebook."
        self.history_notebook_editor_set_content(test_content)

        self.components.history_notebooks.unsaved_indicator.wait_for_visible()
        self.screenshot("history_notebook_unsaved")

        self.history_notebook_save()
        self.screenshot("history_notebook_saved")

        self.history_notebook_manage()
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
        self.navigate_to_history_notebooks()
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

        self.navigate_to_history_notebooks()
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
        self.navigate_to_history_notebooks()
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

        self.navigate_to_history_notebooks()
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

        self.navigate_to_history_notebooks()
        self.history_notebook_assert_item_count(2)

        # Delete via API, then go home and navigate back via menu
        self.dataset_populator.delete_history_notebook(history_id, nb2["id"])
        self.home()
        self.navigate_to_history_notebooks()

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

    # --- Phase 5: Window Manager Integration Tests ---

    @selenium_test
    @managed_history
    def test_notebook_opens_in_window_when_wm_active(self):
        """With WM active, selecting notebook from list opens it in a WinBox."""
        history_id = self.current_history_id()
        self.dataset_populator.new_history_notebook(history_id, title="Window Test", content="# Windowed Notebook")

        self.window_manager_enable()
        assert self.window_manager_window_count() == 0

        self.navigate_to_history_notebooks()
        self.history_notebook_assert_item_count(1)

        # Click the notebook -- should open in WinBox, not navigate
        self.components.history_notebooks.notebook_item.wait_for_and_click()
        self.window_manager_wait_for_window_count(1)

        titles = self.window_manager_get_titles()
        assert any("Window Test" in t for t in titles)

        # List should still be visible (router.push intercepted by WM)
        self.components.history_notebooks.list.wait_for_visible()
        self.screenshot("history_notebook_in_winbox")

    @selenium_test
    @managed_history
    def test_notebook_window_shows_rendered_content(self):
        """Windowed notebook shows rendered markdown, not editor."""
        history_id = self.current_history_id()
        self.dataset_populator.new_history_notebook(
            history_id, title="Render Test", content="# Hello World\n\nSome analysis notes."
        )

        self.window_manager_enable()
        self.navigate_to_history_notebooks()
        self.components.history_notebooks.notebook_item.wait_for_and_click()
        self.window_manager_wait_for_window_count(1)

        with self.winbox_frame(0):
            # Should see rendered markdown (Markdown.vue), not editor
            self.wait_for_selector_visible(".markdown-wrapper")
            # Should NOT see editor or toolbar
            self.wait_for_selector_absent_or_hidden("[data-description='notebook toolbar']")
            self.wait_for_selector_absent_or_hidden("[data-description='history notebook editor']")
            self.screenshot("history_notebook_window_rendered")

    @selenium_test
    @managed_history
    def test_notebook_normal_navigation_when_wm_disabled(self):
        """With WM disabled, selecting notebook navigates to editor normally."""
        history_id = self.current_history_id()
        self.dataset_populator.new_history_notebook(history_id, title="Normal Nav", content="# Editor Test")

        self.window_manager_disable()

        self.navigate_to_history_notebooks()
        self.history_notebook_assert_item_count(1)
        self.components.history_notebooks.notebook_item.wait_for_and_click()

        # Should navigate to editor, NOT open window
        self.components.history_notebooks.editor.wait_for_visible()
        assert self.window_manager_window_count() == 0
        self.screenshot("history_notebook_normal_nav_wm_off")

    @selenium_test
    @managed_history
    def test_notebook_window_with_embedded_dataset(self):
        """Windowed notebook renders embedded dataset displays."""
        history_id = self.current_history_id()
        self.perform_upload(self.get_filename("1.fasta"))
        self.history_panel_wait_for_hid_ok(1)

        content = "# Analysis\n\n```galaxy\nhistory_dataset_display(hid=1)\n```\n"
        self.dataset_populator.new_history_notebook(history_id, title="Dataset Embed", content=content)

        self.window_manager_enable()
        self.navigate_to_history_notebooks()
        self.components.history_notebooks.notebook_item.wait_for_and_click()
        self.window_manager_wait_for_window_count(1)

        with self.winbox_frame(0):
            self.wait_for_selector_visible(".markdown-wrapper")
            self.wait_for_selector_visible(".embedded-dataset")
            self.screenshot("history_notebook_window_dataset_embedded")

    @selenium_test
    @managed_history
    def test_multiple_notebook_windows(self):
        """Opening multiple notebooks creates multiple WinBox windows."""
        history_id = self.current_history_id()
        self.dataset_populator.new_history_notebook(history_id, title="First NB")
        self.dataset_populator.new_history_notebook(history_id, title="Second NB")

        self.window_manager_enable()
        self.navigate_to_history_notebooks()
        self.history_notebook_assert_item_count(2)

        # Open first notebook
        items = self.components.history_notebooks.notebook_item.all()
        items[0].click()
        self.sleep_for(self.wait_types.UX_RENDER)
        self.window_manager_wait_for_window_count(1)

        # Open second notebook
        items = self.components.history_notebooks.notebook_item.all()
        items[1].click()
        self.sleep_for(self.wait_types.UX_RENDER)
        self.window_manager_wait_for_window_count(2)

        titles = self.window_manager_get_titles()
        assert len(titles) == 2
        self.screenshot("history_notebook_multiple_windows")

    # --- Phase 6: Revision UI Tests ---

    @selenium_test
    @managed_history
    def test_revision_list_visible_after_save(self):
        """After saving, revision button shows count; click opens revision list."""
        history_id = self.current_history_id()
        self.dataset_populator.new_history_notebook(history_id, title="Rev Test", content="V1")

        self.navigate_to_history_notebooks()
        self.history_notebook_assert_item_count(1)
        self.components.history_notebooks.notebook_item.wait_for_and_click()
        self.components.history_notebooks.editor.wait_for_visible()

        self.history_notebook_open_revisions()
        self.history_notebook_assert_revision_count(1)
        self.screenshot("history_notebook_revision_list")

    @selenium_test
    @managed_history
    def test_revision_restore(self):
        """Restore to old revision updates editor content."""
        history_id = self.current_history_id()
        nb = self.dataset_populator.new_history_notebook(history_id, title="Restore Test", content="Original")
        self.dataset_populator.update_history_notebook(history_id, nb["id"], content="Modified")

        self.navigate_to_history_notebooks()
        self.components.history_notebooks.notebook_item.wait_for_and_click()
        self.components.history_notebooks.editor.wait_for_visible()

        self.history_notebook_open_revisions()
        # Click restore on the oldest revision (last in the list)
        restore_buttons = self.components.history_notebooks.restore_revision_button.all()
        restore_buttons[-1].click()
        self.sleep_for(self.wait_types.UX_RENDER)

        editor = self.components.history_notebooks.markdown_editor
        assert "Original" in editor.wait_for_value()
        self.screenshot("history_notebook_revision_restored")

    @selenium_test
    @managed_history
    def test_revision_count_increases_after_save(self):
        """Saving creates a new revision, count increases."""
        self.navigate_to_history_notebooks()
        self.history_notebook_create()
        self.components.history_notebooks.editor.wait_for_visible()

        self.history_notebook_editor_set_content("First save")
        self.history_notebook_save()

        self.history_notebook_editor_set_content("Second save")
        self.history_notebook_save()

        self.history_notebook_open_revisions()
        self.history_notebook_assert_revision_count(3)  # initial + 2 saves
        self.screenshot("history_notebook_revision_count")

    @selenium_test
    @managed_history
    def test_revision_preview(self):
        """Clicking a revision shows its rendered content."""
        history_id = self.current_history_id()
        nb = self.dataset_populator.new_history_notebook(history_id, title="Preview", content="# Old Content")
        self.dataset_populator.update_history_notebook(history_id, nb["id"], content="# New Content")

        self.navigate_to_history_notebooks()
        self.components.history_notebooks.notebook_item.wait_for_and_click()
        self.components.history_notebooks.editor.wait_for_visible()

        self.history_notebook_open_revisions()
        # Click the oldest revision row to preview
        items = self.components.history_notebooks.revision_item.all()
        items[-1].click()
        self.components.history_notebooks.revision_view.wait_for_visible()
        self.screenshot("history_notebook_revision_preview")

    # --- Phase 7: Drag-and-Drop Tests ---

    @selenium_only("seletools drag_and_drop requires Selenium webdriver")
    @selenium_test
    @managed_history
    def test_drag_dataset_to_notebook_editor(self):
        """Drag a dataset from history panel and drop on notebook editor."""
        from seletools.actions import drag_and_drop

        self.perform_upload(self.get_filename("1.fasta"))
        self.history_panel_wait_for_hid_ok(1)

        self.navigate_to_history_notebooks()
        self.history_notebook_create()
        self.components.history_notebooks.editor.wait_for_visible()

        # Get handle on the dataset element in history panel
        dataset_selector = self.history_panel_wait_for_hid_state(1, "ok")
        dataset_element = dataset_selector.wait_for_visible()

        # Get handle on the markdown textarea
        editor = self.components.history_notebooks.markdown_editor.wait_for_visible()

        # Perform drag and drop
        drag_and_drop(self.driver, source=dataset_element, target=editor)
        self.sleep_for(self.wait_types.UX_RENDER)

        # Verify the directive was inserted
        value = self.components.history_notebooks.markdown_editor.wait_for_value()
        assert "history_dataset_display" in value
        assert "hid=1" in value
        self.screenshot("history_notebook_drag_drop_dataset")

    @selenium_only("seletools drag_and_drop requires Selenium webdriver")
    @selenium_test
    @managed_history
    def test_drag_drop_visual_feedback(self):
        """Verify visual feedback during drag over notebook editor."""
        self.perform_upload(self.get_filename("1.fasta"))
        self.history_panel_wait_for_hid_ok(1)

        self.navigate_to_history_notebooks()
        self.history_notebook_create()
        self.components.history_notebooks.editor.wait_for_visible()

        dataset_selector = self.history_panel_wait_for_hid_state(1, "ok")
        dataset_element = dataset_selector.wait_for_visible()
        editor = self.components.history_notebooks.markdown_editor.wait_for_visible()

        # Start drag (click and hold, move to editor)
        ac = self.action_chains()
        ac.click_and_hold(dataset_element).move_to_element(editor).perform()
        self.sleep_for(self.wait_types.UX_RENDER)

        # Check that the editor has the highlight class
        classes = editor.get_attribute("class")
        assert "notebook-dragover-success" in classes
        self.screenshot("history_notebook_drag_over_highlight")

        # Release to clean up
        ac.release().perform()
