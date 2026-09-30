from .framework import (
    managed_history,
    RunsWorkflows,
    selenium_test,
    SeleniumTestCase,
)

SUBMISSION_BOUND_TOOL = "license_agreement_path_tool"
LICENSE_ID = "license_agreement_path"

SINGLE_STEP_WORKFLOW = f"""
class: GalaxyWorkflow
steps:
  licensed:
    tool_id: {SUBMISSION_BOUND_TOOL}
    state:
      input: x
"""

NESTED_WORKFLOW = f"""
class: GalaxyWorkflow
steps:
  nested:
    run:
      class: GalaxyWorkflow
      steps:
        licensed:
          tool_id: {SUBMISSION_BOUND_TOOL}
          state:
            input: x
"""

REPEATED_STEP_WORKFLOW = f"""
class: GalaxyWorkflow
steps:
  first:
    tool_id: {SUBMISSION_BOUND_TOOL}
    state:
      input: x
  second:
    tool_id: {SUBMISSION_BOUND_TOOL}
    state:
      input: y
"""


class TestWorkflowLicenseAgreement(SeleniumTestCase, RunsWorkflows):
    def setup_with_driver(self):
        super().setup_with_driver()
        # A fresh user per test, so acceptances never carry over between tests.
        self.register()

    @selenium_test
    @managed_history
    def test_workflow_run_form_prompts_for_step_licenses(self):
        self.workflow_run_open_workflow(SINGLE_STEP_WORKFLOW)
        agreement = self.components.tool_form.license_agreement(license_id=LICENSE_ID).wait_for_visible()
        assert "I certify that I am not using this tool for commercial purposes." in agreement.text
        self.components.workflow_run.run_workflow_disabled.wait_for_present()
        self.screenshot("workflow_license_agreement_prompt")
        self._affirm_and_run()
        self._wait_for_licensed_jobs(1)

    @selenium_test
    @managed_history
    def test_workflow_run_form_prompts_for_subworkflow_licenses(self):
        self.workflow_run_open_workflow(NESTED_WORKFLOW)
        self.components.tool_form.license_agreement(license_id=LICENSE_ID).wait_for_visible()
        self.components.workflow_run.run_workflow_disabled.wait_for_present()
        self._affirm_and_run()
        self._wait_for_licensed_jobs(1)

    @selenium_test
    @managed_history
    def test_workflow_blocked_until_all_accepted(self):
        self.workflow_run_open_workflow(REPEATED_STEP_WORKFLOW)
        tool_form = self.components.tool_form
        tool_form.license_agreement(license_id=LICENSE_ID).wait_for_visible()
        # Both steps declare the same agreement - it is prompted for once.
        assert len(self.find_elements_by_selector(".tool-license-agreement")) == 1
        self.components.workflow_run.run_workflow_disabled.wait_for_present()
        self._affirm_and_run()
        self._wait_for_licensed_jobs(2)

    @selenium_test
    @managed_history
    def test_workflow_one_time_acceptance_does_not_persist(self):
        name = self.workflow_upload_yaml_with_random_name(SINGLE_STEP_WORKFLOW)
        self.workflow_run_with_name(name)
        self._affirm_and_run()
        self._wait_for_licensed_jobs(1)

        self.workflow_run_with_name(name)
        self.components.tool_form.license_affirm(license_id=LICENSE_ID).wait_for_visible()
        self.components.workflow_run.run_workflow_disabled.wait_for_present()
        assert self.license_agreements_populator.list_license_acceptances(include_history=True)["history"] == []

    def _affirm_and_run(self):
        self.components.tool_form.license_affirm(license_id=LICENSE_ID).wait_for_and_click()
        self.wait_for_selector_absent(f'input[data-test-id="license-affirm-{LICENSE_ID}-input"]:not(:checked)')
        self.workflow_run_submit()

    def _wait_for_licensed_jobs(self, count: int):
        history_id = self.current_history_id()

        def licensed_jobs():
            response = self.dataset_populator._get(
                "jobs", data={"history_id": history_id, "tool_id": SUBMISSION_BOUND_TOOL, "state": "ok"}
            )
            response.raise_for_status()
            jobs = response.json()
            return jobs if len(jobs) == count else None

        self._wait_on(licensed_jobs, f"{count} licensed job(s) to complete")
