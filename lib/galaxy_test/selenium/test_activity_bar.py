from .framework import (
    selenium_test,
    SeleniumTestCase,
)


class TestActivityBar(SeleniumTestCase):
    ensure_registered = True

    @selenium_test
    def test_hide_and_show_activity(self):
        self.home()
        activity_bar = self.components.activity_bar
        libraries = activity_bar.item(id="libraries")
        libraries.wait_for_visible()

        activity_bar.more.wait_for_and_click()
        activity_bar.settings.hide(title="Libraries").wait_for_and_click()
        libraries.wait_for_absent_or_hidden()
        self.screenshot("activity_bar_libraries_hidden")

        self.home()
        libraries.assert_absent_or_hidden()

        activity_bar.more.wait_for_and_click()
        activity_bar.settings.show(title="Libraries").wait_for_and_click()
        libraries.wait_for_visible()
