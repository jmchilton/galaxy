"""workflow_index_open_with_name picks the card titled exactly NAME once the search has narrowed the list."""

from types import SimpleNamespace

from selenium.common.exceptions import StaleElementReferenceException

from galaxy.selenium.navigates_galaxy import (
    NavigatesGalaxy,
    workflow_search_term,
)


class _Card:
    def __init__(self, title, stale=False):
        self.title, self.stale = title, stale

    def find_element(self, by, selector):
        if self.stale:
            raise StaleElementReferenceException("card re-rendered")
        return SimpleNamespace(text=self.title)


def _index(*cards):
    return SimpleNamespace(
        components=SimpleNamespace(workflows=SimpleNamespace(workflow_card=SimpleNamespace(all=lambda: list(cards))))
    )


def test_card_titled_exactly_is_chosen_over_a_longer_match():
    exact = _Card("gxui editor 1")
    assert NavigatesGalaxy._workflow_card_named(_index(_Card("gxui editor 12"), exact), "gxui editor 1") is exact


def test_no_card_while_the_list_is_unfiltered_or_re_rendering():
    assert NavigatesGalaxy._workflow_card_named(_index(_Card("other")), "gxui editor 1") is None
    assert NavigatesGalaxy._workflow_card_named(_index(_Card("gxui editor 1", stale=True)), "gxui editor 1") is None


def test_search_term_leaves_out_what_the_search_reads_as_a_filter():
    name = "GTN Training: Workflow Reports - Galaxy 101 For Everyone (imported from URL)"
    assert workflow_search_term(name) == "Workflow Reports - Galaxy 101 For Everyone (imported from URL)"
    assert workflow_search_term("gxui editor 1") == "gxui editor 1"
