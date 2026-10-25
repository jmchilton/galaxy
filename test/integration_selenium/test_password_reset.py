from galaxy_test.driver.integration_util import ConfiguresMockEmails
from .framework import (
    selenium_test,
    SeleniumIntegrationTestCase,
)


class TestPasswordResetSeleniumIntegration(SeleniumIntegrationTestCase, ConfiguresMockEmails):
    @classmethod
    def handle_galaxy_config_kwds(cls, config):
        super().handle_galaxy_config_kwds(config)
        cls._configure_mock_emails(config)

    @selenium_test
    def test_reset_password_from_emailed_link(self):
        email = self._get_random_email(domain="example.org")
        self.register(email)
        self.logout_if_needed()
        assert "confirmation email" in self.request_password_reset(email)
        link = self._read_password_reset_link(email)
        new_password = self._get_random_password()
        self.reset_password_from_link(link, new_password)
        # saving logs the user in
        self.wait_for_logged_in()
        self.screenshot("password_reset_saved")
        self.logout_if_needed()
        self.submit_login(email, new_password)
