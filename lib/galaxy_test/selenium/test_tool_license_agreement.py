from .framework import (
    managed_history,
    selenium_test,
    SeleniumTestCase,
)

SUBMISSION_BOUND_TOOL = "license_agreement_path_tool"
USER_BOUND_TOOL = "license_agreement_variant_tool"
MULTI_TOOL = "license_agreement_multi_tool"
LICENSE_ID = "license_agreement_path"
INLINE_LICENSE_ID = "license_agreement_inline"


class TestToolLicenseAgreement(SeleniumTestCase):
    def setup_with_driver(self):
        super().setup_with_driver()
        # A fresh user per test, so acceptances never carry over between tests.
        self.register()

    @selenium_test
    @managed_history
    def test_tool_form_blocks_until_accepted(self):
        self.tool_open(SUBMISSION_BOUND_TOOL)
        tool_form = self.components.tool_form
        agreement = tool_form.license_agreement(license_id=LICENSE_ID).wait_for_visible()
        assert "I certify that I am not using this tool for commercial purposes." in agreement.text
        # Submission-bound agreements can only be accepted for one run.
        tool_form.license_remember(license_id=LICENSE_ID).assert_absent()
        tool_form.execute_disabled.wait_for_present()
        self.screenshot("tool_license_agreement_prompt")

        self._affirm(LICENSE_ID)
        tool_form.execute_disabled.wait_for_absent()
        self.tool_form_execute()
        self.history_panel_wait_for_hid_ok(1)

    @selenium_test
    def test_license_terms_viewable_before_accepting(self):
        self.tool_open(SUBMISSION_BOUND_TOOL)
        tool_form = self.components.tool_form
        tool_form.license_terms_toggle(license_id=LICENSE_ID).wait_for_visible()
        tool_form.license_terms(license_id=LICENSE_ID).assert_absent()
        tool_form.license_terms_toggle(license_id=LICENSE_ID).wait_for_and_click()
        terms = tool_form.license_terms(license_id=LICENSE_ID).wait_for_visible()
        assert "This software may be used free of charge for non-commercial research" in terms.text
        self.screenshot("tool_license_agreement_terms")

    @selenium_test
    @managed_history
    def test_acceptance_persists_across_sessions(self):
        email = self.get_user_email()
        self.tool_open(USER_BOUND_TOOL)
        tool_form = self.components.tool_form
        self._affirm(LICENSE_ID)
        tool_form.license_remember(license_id=LICENSE_ID).wait_for_and_click()
        self.tool_form_execute()
        self.history_panel_wait_for_hid_ok(1)

        self.logout()
        self.submit_login(email)
        self.tool_open(USER_BOUND_TOOL)
        tool_form.license_accepted(license_id=LICENSE_ID).wait_for_visible()
        tool_form.license_affirm(license_id=LICENSE_ID).assert_absent()
        tool_form.execute_disabled.wait_for_absent()

    @selenium_test
    @managed_history
    def test_one_time_acceptance_does_not_persist(self):
        self.tool_open(USER_BOUND_TOOL)
        tool_form = self.components.tool_form
        self._affirm(LICENSE_ID)
        self.tool_form_execute()
        self.history_panel_wait_for_hid_ok(1)

        self.tool_open(USER_BOUND_TOOL)
        tool_form.license_affirm(license_id=LICENSE_ID).wait_for_visible()
        tool_form.execute_disabled.wait_for_present()
        assert self.license_agreements_populator.list_license_acceptances(include_history=True)["history"] == []

    @selenium_test
    def test_multi_agreement_partial_acceptance_blocks(self):
        self.tool_open(MULTI_TOOL)
        tool_form = self.components.tool_form
        self._affirm(INLINE_LICENSE_ID)
        # Rendered after the first affirmation - the second agreement still blocks the run.
        tool_form.execute_disabled.wait_for_present()
        self._affirm(LICENSE_ID)
        tool_form.execute_disabled.wait_for_absent()

    def _affirm(self, license_id: str):
        self.components.tool_form.license_affirm(license_id=license_id).wait_for_and_click()
        self.wait_for_selector_absent(f'input[data-test-id="license-affirm-{license_id}-input"]:not(:checked)')
