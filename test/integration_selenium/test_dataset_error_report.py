import json
import os
from typing import ClassVar

from .framework import (
    managed_history,
    selenium_test,
    SeleniumIntegrationTestCase,
)


class TestDatasetErrorReportSeleniumIntegration(SeleniumIntegrationTestCase):
    ensure_registered = True
    framework_tool_and_types = True
    email_directory: ClassVar[str]

    @classmethod
    def handle_galaxy_config_kwds(cls, config):
        super().handle_galaxy_config_kwds(config)
        cls.email_directory = cls._test_driver.mkdtemp()
        config["email_from"] = "galaxy-noreply@example.com"
        config["error_email_to"] = "galaxy-errors@example.com"
        config["smtp_server"] = f"mock_emails_to_path://{cls.email_directory}/email.json"

    @selenium_test
    @managed_history
    def test_report_error_from_history_item(self):
        history_id = self.current_history_id()
        inputs = {"stdoutmsg": "", "stderrmsg": "error: column 9 does not exist", "exit_code": "6"}
        response = self.dataset_populator.run_tool("detect_errors", inputs, history_id)
        self.dataset_populator.wait_for_history(history_id, assert_ok=False)
        hid = response["outputs"][0]["hid"]
        self.history_panel_wait_for_hid_state(hid, "error")

        self.history_panel_item_show_error(hid)
        dataset_error = self.components.dataset_error
        assert dataset_error.tool_id.wait_for_text() == "detect_errors"
        assert "error: column 9 does not exist" in dataset_error.tool_stderr.wait_for_text()
        self.screenshot("dataset_error_report_form")

        result = self.submit_email_report("Filtered on a column my data does not have.")
        assert "Your error report has been sent" in result, result
        self.components.email_report._.wait_for_absent_or_hidden()
        self.screenshot("dataset_error_report_sent")

        with open(os.path.join(self.email_directory, "email.json")) as f:
            email = json.load(f)
        assert email["to"].startswith("galaxy-errors@example.com"), email["to"]
        assert "detect_errors" in email["subject"], email["subject"]
        assert "Filtered on a column my data does not have." in email["body"]
