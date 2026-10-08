"""workflow_search_term leaves out what the workflow list's search reads as a filter."""

from galaxy.selenium.navigates_galaxy import workflow_search_term


def test_search_term_leaves_out_what_the_search_reads_as_a_filter():
    name = "GTN Training: Workflow Reports - Galaxy 101 For Everyone (imported from URL)"
    assert workflow_search_term(name) == "Workflow Reports - Galaxy 101 For Everyone (imported from URL)"
    assert workflow_search_term("gxui editor 1") == "gxui editor 1"
