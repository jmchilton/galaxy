from .framework import (
    retry_assertion_during_transitions,
    selenium_test,
    SeleniumTestCase,
)


class TestDatasetsList(SeleniumTestCase):
    @selenium_test
    def test_datasets_list_spans_histories(self):
        # A fresh user, so the list holds only this test's datasets.
        self.register(self._get_random_email())
        for name in ("first", "second"):
            history_id = self.dataset_populator.new_history(name=f"{name} history")
            self.dataset_populator.new_dataset(history_id, content=f"{name}\n", name=f"{name}.txt", wait=True)

        self.navigate_to_datasets_list()

        @retry_assertion_during_transitions
        def assert_rows(expected):
            assert self.datasets_list_rows() == expected

        second = {"name": "second.txt", "history": "second history", "extension": "txt"}
        first = {"name": "first.txt", "history": "first history", "extension": "txt"}
        # newest first
        assert_rows([second, first])
        self.screenshot("datasets_list")

        self.datasets_list_search("first")
        assert_rows([first])
