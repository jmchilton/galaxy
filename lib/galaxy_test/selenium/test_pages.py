from galaxy.selenium.keys import Key
from galaxy.selenium.smart_components import SmartTarget
from galaxy_test.base.workflow_fixtures import (
    WORKFLOW_WITH_BAD_COLUMN_PARAMETER,
    WORKFLOW_WITH_OLD_TOOL_VERSION,
)
from .framework import (
    managed_history,
    retry_assertion_during_transitions,
    selenium_test,
    SeleniumTestCase,
)
from .upload_activity_helpers import UsesUploadActivity


class TestPages(SeleniumTestCase, UsesUploadActivity):
    ensure_registered = True

    @selenium_test
    @managed_history
    def test_simple_page_creation_edit_and_view(self):
        # Upload a file to test embedded object stuff
        test_path = self.get_filename("1.fasta")
        self.upload_context("local-file").stage_local_file(test_path).start()
        self.history_panel_wait_for_hid_ok(1)
        self.navigate_to_pages()
        self.screenshot("pages_grid")
        page_name = self.create_page_and_edit(screenshot_name="pages_create_form")
        self.screenshot("pages_editor_new")
        editor = self._page_editor
        editor.markdown_editor.wait_for_and_send_keys("moo\n\n\ncow\n\n")
        editor.embed_dataset.wait_for_and_click()
        self.screenshot("pages_editor_embed_dataset_dialog")
        editor.dataset_selector.wait_for_and_click()
        self.sleep_for(self.wait_types.UX_RENDER)
        editor.save.wait_for_and_click()
        self.screenshot("pages_editor_saved")
        self.page_open_and_screenshot(page_name, "page_view_with_embedded_dataset")

    @selenium_test
    @managed_history
    def test_workflow_problem_display(self):
        workflow_populator = self.workflow_populator
        problem_workflow_1_id = workflow_populator.upload_yaml_workflow(
            WORKFLOW_WITH_OLD_TOOL_VERSION, exact_tools=True
        )
        problem_workflow_2_id = workflow_populator.upload_yaml_workflow(
            WORKFLOW_WITH_BAD_COLUMN_PARAMETER, exact_tools=True
        )
        self.navigate_to_pages()
        page_name = self.create_page_and_edit()
        editor = self._page_editor
        editor.markdown_editor.wait_for_and_send_keys("moo\n\n\ncow\n\n")
        editor.embed_workflow_display.wait_for_and_click()
        self.screenshot("pages_editor_embed_workflow_dialog")
        editor.workflow_selection(id=problem_workflow_1_id).wait_for_and_click()
        self.sleep_for(self.wait_types.UX_RENDER)
        editor.embed_workflow_display.wait_for_and_click()
        editor.workflow_selection(id=problem_workflow_2_id).wait_for_and_click()
        self.sleep_for(self.wait_types.UX_RENDER)
        editor.save.wait_for_and_click()
        self.page_open_and_screenshot(page_name, "page_view_with_workflow_problems")

    @selenium_test
    @managed_history
    def test_history_links(self):
        new_history_name = self._get_random_name()
        self.history_panel_rename(new_history_name)
        self.current_history_publish()
        history_id = self.current_history_id()
        self.navigate_to_pages()
        page_name = self.create_page_and_edit()
        editor = self._page_editor
        editor.history_link.wait_for_and_click()
        editor.history_selection(id=history_id).wait_for_and_click()
        self.sleep_for(self.wait_types.UX_RENDER)
        editor.save.wait_for_and_click()
        self.page_open_and_screenshot(page_name, "page_view_with_history_link")
        view = self.components.pages.view
        view.history_link(history_id=history_id).wait_for_and_click()
        self.sleep_for(self.wait_types.UX_RENDER)
        self.navigate_to_histories_page()
        history_names = self.get_history_titles(1)
        assert f"Copy of '{new_history_name}'" in history_names

    @property
    def _page_editor(self):
        return self.components.pages.editor

    # --- Standalone page unified editor tests ---

    @selenium_test
    @managed_history
    def test_standalone_page_unified_editor_round_trip(self):
        """Core round-trip: edit regular page through PageEditorView, save, reload."""
        slug = self._get_random_name(prefix="roundtrip")
        page = self.dataset_populator.new_page(slug=slug, content_format="markdown", content="# Starter")
        self.navigate_to_page_editor(page["id"])

        self.components.pages.history.toolbar.wait_for_visible()
        editor = self.components.pages.history.markdown_editor
        assert "Starter" in editor.wait_for_value()

        self.history_page_editor_set_content("# Full Round Trip\n\nContent from unified editor.")
        self.components.pages.history.unsaved_indicator.wait_for_visible()
        self.history_page_save()
        self.components.pages.history.unsaved_indicator.assert_absent_or_hidden_after_transitions()

        self.home()
        self.navigate_to_page_editor(page["id"])

        assert "Full Round Trip" in editor.wait_for_value()
        self.screenshot("standalone_page_round_trip")

    @selenium_test
    def test_cell_editor_menus_return_focus_after_keyboard_selection(self):
        """Choosing a cell menu option by keyboard closes the menu and refocuses the button that opened it."""
        slug = self._get_random_name(prefix="cellmenus")
        page = self.dataset_populator.new_page(slug=slug, content_format="markdown", content="# Starter")
        self.navigate_to_page_editor(page["id"])
        self.components.markdown_cell_editor.editor_mode_button.wait_for_and_click()
        # Clone and Insert Cell Below add cells after this one, so index 0 stays this cell.
        cell = self.components.markdown_cell_editor.cell(index=0)
        cell.toggle_button.wait_for_and_click()

        for key in (Key.ENTER, Key.SPACE):
            # Both keys show the same menus; screenshot them once.
            screenshot = key is Key.ENTER
            self._markdown_cell_menu_select_with_key(
                cell.actions_button,
                cell.actions_option(title="Clone"),
                cell.actions_menu,
                key,
                "pages_cell_editor_actions_menu" if screenshot else None,
            )
            self._markdown_cell_menu_select_with_key(
                cell.insert_button,
                cell.insert_option(title="Heading 1"),
                cell.insert_menu,
                key,
                "pages_cell_editor_insert_menu" if screenshot else None,
            )

        # Focus must follow the moved cell. Cells are keyed by position, so the menu alone would
        # refocus the actions button at the old position, which now belongs to the open cell swapped in.
        next_cell = self.components.markdown_cell_editor.cell(index=1)
        self._markdown_cell_menu_select_with_key(
            cell.actions_button,
            cell.actions_option(title="Move Down"),
            cell.actions_menu,
            Key.ENTER,
            focused=next_cell.actions_button,
        )
        self._markdown_cell_menu_select_with_key(
            next_cell.actions_button,
            next_cell.actions_option(title="Move Up"),
            next_cell.actions_menu,
            Key.SPACE,
            focused=cell.actions_button,
        )

    def _markdown_cell_menu_select_with_key(
        self,
        button: SmartTarget,
        option: SmartTarget,
        menu: SmartTarget,
        key: Key,
        screenshot_name: str | None = None,
        focused: SmartTarget | None = None,
    ) -> None:
        """Choose ``option`` by ``key`` and check the menu closes and focus lands on ``focused`` (default ``button``)."""
        button.wait_for_and_click()
        option_element = option.wait_for_visible()
        self.screenshot_if(screenshot_name)
        self.press(key, element=option_element)
        menu.wait_for_absent_or_hidden()
        # Deliberate sleep: the menu must stay closed, and no element appears to wait on.
        # A key press that also activated the refocused button would reopen the menu in this window.
        self.sleep_for(self.wait_types.UX_RENDER)
        menu.assert_absent_or_hidden()
        expected_focus = (focused or button).wait_for_visible()
        assert self.execute_script("return document.activeElement === arguments[0];", expected_focus)

    @selenium_test
    @managed_history
    def test_standalone_page_revisions(self):
        """Revisions: UI saves increase count, restore restores oldest content."""
        slug = self._get_random_name(prefix="revisions")
        page = self.dataset_populator.new_page(slug=slug, content_format="markdown", content="# Initial")
        self.navigate_to_page_editor(page["id"])

        self.history_page_editor_set_content("# Save 1")
        self.history_page_save()

        self.history_page_editor_set_content("# Save 2")
        self.history_page_save()

        self.history_page_open_revisions()
        self.history_page_assert_revision_count(3)  # initial + 2 saves

        # Click restore on oldest revision (last in list)
        restore_buttons = self.components.pages.history.restore_revision_button.all()
        restore_buttons[-1].click()

        editor = self.components.pages.history.markdown_editor

        @retry_assertion_during_transitions
        def assert_restored():
            assert "Initial" in editor.wait_for_value()

        assert_restored()
        self.screenshot("standalone_page_revision_restore")

    @selenium_test
    @managed_history
    def test_standalone_page_back_button_returns_to_grid(self):
        """Back button navigates from editor to pages grid."""
        slug = self._get_random_name(prefix="backbtn")
        page = self.dataset_populator.new_page(slug=slug, content_format="markdown", content="# Back Test")
        self.navigate_to_page_editor(page["id"])

        self.components.pages.history.toolbar.wait_for_visible()
        self.components.pages.history.back_button.wait_for_and_click()
        self.sleep_for(self.wait_types.UX_TRANSITION)

        # Should be on the pages grid
        self.components.pages.activity.wait_for_visible()
        self.screenshot("standalone_page_back_to_grid")

    @selenium_test
    @managed_history
    def test_standalone_page_revision_diff(self):
        """Two diff modes on standalone page: compare to previous and compare to current."""
        slug = self._get_random_name(prefix="diff")
        page = self.dataset_populator.new_page(slug=slug, content_format="markdown", content="# Start\n\nAlpha")
        self.dataset_populator.update_history_page(page["id"], content="# Start\n\nBeta")

        self.navigate_to_page_editor(page["id"])

        self.history_page_open_revisions()
        self.history_page_assert_revision_count(2)

        # Click newest revision
        items = self.components.pages.history.revision_item.all()
        items[0].click()
        self.components.pages.history.revision_view.wait_for_visible()

        # Newest: "Compare to Current" hidden, "Compare to Previous" visible
        self.components.pages.history.revision_compare_current_button.assert_absent_or_hidden()
        self.components.pages.history.revision_compare_previous_button.wait_for_visible()

        # Click "Compare to Previous"
        self.components.pages.history.revision_compare_previous_button.wait_for_and_click()
        self.components.pages.history.revision_diff_view.wait_for_visible()

        diff_text = self.components.pages.history.revision_diff_view.wait_for_visible().text
        assert "Beta" in diff_text or "Alpha" in diff_text

        # Go back, click oldest revision
        self.history_page_open_revisions()
        items = self.components.pages.history.revision_item.all()
        items[-1].click()
        self.components.pages.history.revision_view.wait_for_visible()

        # Wait for the newly selected revision before asserting what disappeared.
        self.components.pages.history.revision_compare_current_button.wait_for_visible()
        self.components.pages.history.revision_compare_previous_button.assert_absent_or_hidden()

        # Click "Compare to Current"
        self.components.pages.history.revision_compare_current_button.wait_for_and_click()
        self.components.pages.history.revision_diff_view.wait_for_visible()
        self.screenshot("standalone_page_revision_diff")

    @selenium_test
    @managed_history
    def test_standalone_toolbar_shows_permissions_not_history_controls(self):
        """Standalone editor shows correct toolbar: permissions, save-view, no history text."""
        slug = self._get_random_name(prefix="toolbar")
        page = self.dataset_populator.new_page(slug=slug, content_format="markdown", content="# Toolbar Test")
        self.navigate_to_page_editor(page["id"])

        self.components.pages.history.toolbar.wait_for_visible()
        # Standalone controls visible
        self.components.pages.history.save_button.wait_for_visible()
        self.components.pages.history.revisions_button.wait_for_visible()
        self.components.pages.history.preview_button.wait_for_visible()
        self.components.pages.history.permissions_button.wait_for_visible()

        # Back button says "Back to Notebooks" not "This History's Notebooks"
        back_text = self.components.pages.history.back_button.wait_for_text()
        assert "Back to Notebooks" in back_text
        assert "This History's Notebooks" not in back_text
        self.screenshot("standalone_toolbar_controls")
