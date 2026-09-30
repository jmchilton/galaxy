from .framework import (
    managed_history,
    selenium_test,
    SeleniumTestCase,
)

USER_BOUND_TOOL = "license_agreement_variant_tool"
LICENSE_ID = "license_agreement_path"
LICENSE_LABEL = "Test Tool Non-Commercial License"


class TestToolLicenseAsyncFailure(SeleniumTestCase):
    def setup_with_driver(self):
        super().setup_with_driver()
        self.register()

    @selenium_test
    @managed_history
    def test_license_failure_visible_to_user(self):
        populator = self.license_agreements_populator
        accepted = populator.accept_license_agreement(USER_BOUND_TOOL, LICENSE_ID)
        self.tool_open(USER_BOUND_TOOL)
        tool_form = self.components.tool_form
        tool_form.license_accepted(license_id=LICENSE_ID).wait_for_visible()

        # Revoked after the form loaded, so the form still offers Run - the server refuses the submission.
        populator.revoke_license_acceptance(accepted["agreement"]["agreement_hash"])
        self.tool_form_execute()

        error = tool_form.submission_error.wait_for_visible()
        assert LICENSE_LABEL in error.text
        assert "Accept these license agreements on the tool form" in error.text
        self.screenshot("tool_license_submission_refused")
        # The form reloads and prompts for the agreement again.
        tool_form.license_affirm(license_id=LICENSE_ID).wait_for_present()
        assert populator.list_license_acceptances()["accepted"] == []
