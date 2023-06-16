from .framework import (
    managed_history,
    selenium_test,
    SeleniumTestCase,
)


class TestHistoryMultiView(SeleniumTestCase):
    ensure_registered = True

    @selenium_test
    def test_display(self):
        history_id = self.current_history_id()
        input_collection = self.dataset_collection_populator.create_list_in_history(
            history_id, contents=["0", "1", "0", "1"], wait=True
        ).json()
        input_hid = input_collection["outputs"][0]["hid"]
        self.home()
        self.open_history_multi_view()
        hdca_selector = self.history_panel_wait_for_hid_state(input_hid, "ok", multi_history_panel=True)
        self.wait_for_visible(hdca_selector)
        self.screenshot("multi_history_collection")

    @selenium_test
    @managed_history
    def test_list_list_display(self):
        history_id = self.current_history_id()
        method = self.dataset_collection_populator.create_list_of_list_in_history(history_id, wait=True).json
        self.prepare_multi_history_view(method)
        dataset_selector = self.history_panel_wait_for_hid_state(1, None, multi_history_panel=True)
        self.click(dataset_selector)
        dataset_selector = self.history_panel_wait_for_hid_state(3, None, multi_history_panel=True)
        self.click(dataset_selector)
        self.screenshot("multi_history_list_list")

    @selenium_test
    def test_select_by_filtering(self):
        self.home()
        random_name = self._get_random_name(prefix="multiview")
        history_name_foo = random_name + "foo"
        history_name_bar = random_name + "bar"
        history_id_foo = self.history_panel_create_new_with_name(history_name_foo)
        self.history_panel_create_new_with_name(history_name_bar)
        self.open_history_multi_view()
        multi_history_panel = self.components.multi_history_panel
        multi_history_panel.select_link.wait_for_and_click()
        multi_history_panel.history_panel(history_id=history_id_foo).assert_absent()
        multi_history_panel.history_selector_search.wait_for_present()
        multi_history_panel.history_selector_search.wait_for_and_send_keys(history_name_foo)
        entry = multi_history_panel.history_selector_history(history_id=history_id_foo)
        entry.wait_for_present()
        # doesn't work to select right away... click handler not setup yet?
        self.sleep_for(self.wait_types.UX_RENDER)
        entry.wait_for_and_click()
        multi_history_panel.history_selector_change.wait_for_and_click()
        multi_history_panel.history_panel(history_id=history_id_foo).wait_for_present()

    def prepare_multi_history_view(self, collection_populator_method):
        collection = collection_populator_method()
        if "outputs" in collection:
            collection = self.dataset_collection_populator.wait_for_fetched_collection(collection)
        collection_hid = collection["hid"]

        self.home()
        self.open_history_multi_view()
        selector = self.history_panel_wait_for_hid_state(collection_hid, "ok", multi_history_panel=True)
        self.click(selector)
        return selector
