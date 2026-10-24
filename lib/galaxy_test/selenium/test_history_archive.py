from .framework import (
    selenium_test,
    SeleniumTestCase,
)


class TestHistoryArchive(SeleniumTestCase):
    ensure_registered = True

    @selenium_test
    def test_archive_current_history(self):
        name = self._get_random_name(prefix="archive")
        self.history_panel_create_new_with_name(name)
        history_id = self.current_history_id()
        self.history_panel_archive()
        assert self.api_get(f"histories/{history_id}")["archived"]
        self.navigate_to_archived_histories()
        assert name in self.get_history_titles(1)
