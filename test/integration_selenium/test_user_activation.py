import json
import os
import re
from typing import ClassVar

from .framework import (
    selenium_test,
    SeleniumIntegrationTestCase,
)


class TestUserActivationSeleniumIntegration(SeleniumIntegrationTestCase):
    email_directory: ClassVar[str]

    @classmethod
    def handle_galaxy_config_kwds(cls, config):
        super().handle_galaxy_config_kwds(config)
        cls.email_directory = cls._test_driver.mkdtemp()
        config["user_activation_on"] = True
        config["email_from"] = "galaxy-noreply@example.com"
        config["smtp_server"] = f"mock_emails_to_path://{cls.email_directory}/email.json"

    @selenium_test
    def test_register_resend_and_activate(self):
        # user_activation_on also turns on a DNS check of the email's domain.
        email = self._get_random_email(domain="example.org")
        self.register(email)
        inactivity_box = self.components.inactivity_box
        inactivity_box._.wait_for_visible()
        self.screenshot("user_activation_inactive")
        self._activation_link(email)

        os.remove(self._email_path)
        inactivity_box.resend_verification.wait_for_and_click()
        message = self.components._.messages.all.wait_for_visible()
        assert "activation link has been sent again" in message.text, message.text
        link = self._activation_link(email)

        self.navigate_to(link)
        self.home()
        inactivity_box._.assert_absent_or_hidden()
        self.components.masthead.logged_in_only.wait_for_visible()

    @property
    def _email_path(self) -> str:
        return os.path.join(self.email_directory, "email.json")

    def _activation_link(self, email_address: str) -> str:
        with open(self._email_path) as f:
            email = json.load(f)
        assert email["to"] == email_address
        assert email["subject"] == "Galaxy Account Activation"
        match = re.search(r"(https?://[^/\s]+/user/activate\?\S+)", email["body"])
        assert match, f"No activation link found in email body:\n{email['body']}"
        return match.group(1)
