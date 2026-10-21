from galaxy.selenium.upload_activity_helpers import UsesUploadActivity
from .framework import (
    managed_history,
    retry_assertion_during_transitions,
    selenium_test,
    SeleniumTestCase,
)


class TestHistoryOptions(SeleniumTestCase, UsesUploadActivity):
    ensure_registered = True

    @selenium_test
    @managed_history
    def test_options(self):
        self.upload_context("paste-content").stage_paste_content("text content").start()
        menu_selector = self.navigation.history_panel.selectors.options_menu
        self.wait_for_absent_or_hidden(menu_selector)
        self.click_history_options()
        component = self.wait_for_visible(menu_selector)
        self.screenshot("history_options")
        self.send_escape(component)
        self.wait_for_absent_or_hidden(menu_selector)
        hid = 1
        self.history_panel_wait_for_hid_state(hid, "ok")
        self.history_panel_click_item_title(hid=hid, wait=True)
        item_component = self.history_panel_item_body_component(hid=hid)
        item_component.wait_for_visible()
        # Wait for metadata to replace the loading placeholder before testing collapse.
        self.history_panel_item_component(hid=hid).summary.wait_for_visible()
        self.history_panel_click_item_title(hid=hid, wait=True)
        item_component.assert_absent_or_hidden_after_transitions()

    @selenium_test
    @managed_history
    def test_export_tool_references(self):
        history_id = self.current_history_id()
        self.dataset_populator.run_tool("bibtex", {"input1": 8}, history_id)
        self.dataset_populator.wait_for_history(history_id)
        self.home()
        self.click_history_option_tool_references()
        citations = self.components.citations

        @retry_assertion_during_transitions
        def assert_references(*expected):
            text = "\n".join(reference.text for reference in citations._.reference.all())
            for fragment in expected:
                assert fragment in text, f"{fragment!r} not in references: {text}"

        # The tool's own references, and Galaxy's (citation_bibtex) first.
        assert_references("Garrison", "Galaxy for accessible, reproducible, and collaborative data analyses")
        self.screenshot("history_tool_references_apa")
        citations.bibtex_tab.wait_for_and_click()
        assert_references("@misc{Garrison2015", "@article{Galaxy2026")
        self.screenshot("history_tool_references_bibtex")
