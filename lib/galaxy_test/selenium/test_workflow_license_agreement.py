from .framework import (
    managed_history,
    RunsWorkflows,
    selenium_test,
    SeleniumTestCase,
)

SUBMISSION_BOUND_TOOL = "license_agreement_path_tool"
USER_BOUND_TOOL = "license_agreement_variant_tool"
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

NESTED_USER_BOUND_WORKFLOW = f"""
class: GalaxyWorkflow
steps:
  nested:
    run:
      class: GalaxyWorkflow
      steps:
        licensed:
          tool_id: {USER_BOUND_TOOL}
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
        assert len(tool_form.license_agreements.all()) == 1
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

    @selenium_test
    @managed_history
    def test_workflow_remembers_nested_user_bound_agreement(self):
        name = self.workflow_upload_yaml_with_random_name(NESTED_USER_BOUND_WORKFLOW)
        self.workflow_run_with_name(name)
        tool_form = self.components.tool_form
        tool_form.license_agreement(license_id=LICENSE_ID).wait_for_visible()
        self._affirm(LICENSE_ID)
        tool_form.license_remember(license_id=LICENSE_ID).wait_for_and_click()
        self.workflow_run_submit()
        self._wait_for_licensed_jobs(1, tool_id=USER_BOUND_TOOL)

        (acceptance,) = self.license_agreements_populator.list_license_acceptances()["accepted"]
        assert acceptance["event"]["prompting_tool_id"] == USER_BOUND_TOOL
        self.workflow_run_with_name(name)
        tool_form.license_accepted(license_id=LICENSE_ID).wait_for_visible()
        self.components.workflow_run.run_workflow_disabled.wait_for_absent()

    @selenium_test
    @managed_history
    def test_expanded_workflow_run_form_prompts_for_licenses(self):
        self.workflow_run_open_workflow(SINGLE_STEP_WORKFLOW)
        self.workflow_run_ensure_expanded()
        self.components.tool_form.license_agreement(license_id=LICENSE_ID).wait_for_visible()
        self.components.workflow_run.run_workflow_disabled.wait_for_present()
        self._affirm_and_run()
        self._wait_for_licensed_jobs(1)

    def _affirm(self, license_id: str):
        self.components.tool_form.license_affirm(license_id=license_id).wait_for_and_click()
        self.components.tool_form.license_affirm_unchecked(license_id=license_id).wait_for_absent()

    def _affirm_and_run(self):
        self._affirm(LICENSE_ID)
        self.workflow_run_submit()

    def _wait_for_licensed_jobs(self, count: int, tool_id: str = SUBMISSION_BOUND_TOOL):
        history_id = self.current_history_id()

        def licensed_jobs():
            response = self.dataset_populator._get("jobs", data={"history_id": history_id, "tool_id": tool_id})
            response.raise_for_status()
            jobs = response.json()
            failed = [job for job in jobs if job["state"] in ("error", "failed")]
            assert not failed, f"Licensed jobs failed: {failed}"
            done = [job for job in jobs if job["state"] == "ok"]
            return jobs if len(done) == count else None

        self._wait_on(licensed_jobs, f"{count} licensed job(s) to complete")
