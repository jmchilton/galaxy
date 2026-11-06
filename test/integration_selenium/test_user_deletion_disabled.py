from .framework import (
    selenium_test,
    SeleniumIntegrationTestCase,
)


class TestUserDeletionDisabledSeleniumIntegration(SeleniumIntegrationTestCase):
    @classmethod
    def handle_galaxy_config_kwds(cls, config):
        super().handle_galaxy_config_kwds(config)
        config["allow_user_deletion"] = False

    @selenium_test
    def test_delete_account_refused_by_configuration(self):
        email = self._get_random_email()
        self.register(email)
        self.request_account_deletion(email)
        # The modal stays open and explains that the instance does not allow self-deletion.
        preferences = self.components.preferences
        error_text = preferences.delete_account_error.wait_for_text()
        assert "User deletion must be configured on this instance" in error_text, error_text
        assert preferences.delete_account_input.wait_for_value() == email
        # The pending-request lock is released, so the user could try again.
        preferences.delete_account_ok_btn.wait_for_clickable()
        self.screenshot("user_deletion_refused_by_configuration")
        # The account was not deleted, so the user is still logged in.
        self.navigate_to_user_preferences()
        preferences.delete_account.wait_for_visible()
