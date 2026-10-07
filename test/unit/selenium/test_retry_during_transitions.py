"""retry_call_during_transitions: fast transition errors retry; Playwright timeouts already waited."""

import pytest
from selenium.common.exceptions import StaleElementReferenceException

from galaxy.selenium.navigates_galaxy import retry_call_during_transitions

PlaywrightTimeoutError = pytest.importorskip("playwright._impl._errors").TimeoutError


def _always(exception):
    calls = []

    def f():
        calls.append(1)
        raise exception

    return f, calls


def test_stale_elements_retry_every_attempt():
    f, calls = _always(StaleElementReferenceException("stale"))
    try:
        retry_call_during_transitions(f, attempts=10, sleep=0)
    except StaleElementReferenceException:
        pass
    assert len(calls) == 12


def test_a_playwright_timeout_is_retried_once():
    # Each Playwright timeout is a full action timeout of Playwright's own retrying; ten more of them
    # turned one covered click into minutes.
    f, calls = _always(PlaywrightTimeoutError("Locator.click: Timeout 30000ms exceeded."))
    try:
        retry_call_during_transitions(f, attempts=10, sleep=0)
    except PlaywrightTimeoutError:
        pass
    assert len(calls) == 2
