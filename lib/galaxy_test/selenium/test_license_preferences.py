from .framework import (
    selenium_test,
    SeleniumTestCase,
)

USER_BOUND_TOOL = "license_agreement_variant_tool"
LICENSE_ID = "license_agreement_path"


class TestLicensePreferences(SeleniumTestCase):
    def setup_with_driver(self):
        super().setup_with_driver()
        self.register()

    @selenium_test
    def test_accepted_license_listed_in_preferences(self):
        self.license_agreements_populator.accept_license_agreement(USER_BOUND_TOOL, LICENSE_ID)
        self._open_license_agreements()
        management = self.components.license_agreements_management
        acceptance = management.acceptance(license_id=LICENSE_ID).wait_for_visible()
        assert "Test Tool Non-Commercial License" in acceptance.text
        management.terms_toggle(license_id=LICENSE_ID).wait_for_and_click()
        terms = management.terms(license_id=LICENSE_ID).wait_for_visible()
        assert "This software may be used free of charge for non-commercial research" in terms.text
        self.screenshot("license_preferences_accepted")

    @selenium_test
    def test_revoke_from_preferences_reblocks_tool(self):
        self.license_agreements_populator.accept_license_agreement(USER_BOUND_TOOL, LICENSE_ID)
        self._open_license_agreements()
        management = self.components.license_agreements_management
        management.revoke(license_id=LICENSE_ID).wait_for_and_click()
        self.components.confirm_dialog.ok_button.wait_for_and_click()
        management.no_acceptances.wait_for_visible()

        self.tool_open(USER_BOUND_TOOL)
        self.components.tool_form.license_affirm(license_id=LICENSE_ID).wait_for_visible()
        # The prompt renders only for unaccepted agreements, so the button is disabled because of it.
        self.components.tool_form.execute_disabled.wait_for_present()

    @selenium_test
    def test_history_shows_accept_and_revoke_events(self):
        populator = self.license_agreements_populator
        accepted = populator.accept_license_agreement(USER_BOUND_TOOL, LICENSE_ID)
        populator.revoke_license_acceptance(accepted["agreement"]["agreement_hash"])
        self._open_license_agreements()
        management = self.components.license_agreements_management
        management.no_acceptances.wait_for_visible()
        events = management.history_events.all()
        assert [event.get_attribute("data-action") for event in events] == ["accept", "revoke"]
        self.screenshot("license_preferences_history")

    def _open_license_agreements(self):
        self.navigate_to_user_preferences()
        self.components.preferences.manage_license_agreements.wait_for_and_click()
