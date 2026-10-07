"""select_set_value picks the option equal to the value, not the first one containing it."""

import pytest

from galaxy.selenium.navigates_galaxy import NavigatesGalaxy
from .test_has_driver import (
    TestHasDriverImpl,
    TestHasPlaywrightDriverImpl,
)


class _Page:
    select_set_value = NavigatesGalaxy.select_set_value

    def __init__(self, impl):
        self._impl = impl

    def __getattr__(self, name):
        return getattr(self._impl, name)

    def sleep_for(self, wait_type):
        pass


@pytest.fixture(params=["selenium", "playwright"])
def page(request, driver, playwright_resources, base_url):
    impl = (
        TestHasDriverImpl(driver) if request.param == "selenium" else TestHasPlaywrightDriverImpl(playwright_resources)
    )
    impl.navigate_to(f"{base_url}/multiselect.html")
    return _Page(impl)


def test_select_set_value_picks_the_exact_option(page):
    # "txt" is also a substring of metacyto_clr.txt, which the list shows first.
    page.select_set_value("#extension", "txt")
    assert page.find_element_by_selector("#selected").text == "txt"
