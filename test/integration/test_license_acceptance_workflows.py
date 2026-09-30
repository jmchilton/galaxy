import time
from contextlib import contextmanager
from typing import Any

from sqlalchemy import select

from galaxy.model import (
    Job,
    WorkflowInvocationLicenseAcceptanceAssociation,
)
from galaxy_test.base.api_util import random_name
from galaxy_test.base.populators import (
    DatasetPopulator,
    LicenseAgreementsPopulator,
    skip_without_tool,
    WorkflowPopulator,
)
from galaxy_test.driver import integration_util

SUBMISSION_BOUND_TOOL = "license_agreement_path_tool"
USER_BOUND_TOOL = "license_agreement_variant_tool"
DATA_TOOL = "license_agreement_data_tool"
USER_BOUND_DATA_TOOL = "license_agreement_user_data_tool"
LICENSE_ID = "license_agreement_path"

SIMPLE_WORKFLOW = f"""
class: GalaxyWorkflow
inputs:
  unused:
    type: data
    optional: true
steps:
  licensed:
    tool_id: {SUBMISSION_BOUND_TOOL}
    state:
      input: x
"""

SUBWORKFLOW_WORKFLOW = f"""
class: GalaxyWorkflow
inputs:
  unused:
    type: data
    optional: true
steps:
  nested:
    run:
      class: GalaxyWorkflow
      inputs:
        nested_unused:
          type: data
          optional: true
      steps:
        licensed:
          tool_id: {SUBMISSION_BOUND_TOOL}
          state:
            input: x
"""

NESTED_LICENSED = f"""
    run:
      class: GalaxyWorkflow
      steps:
        licensed:
          tool_id: {SUBMISSION_BOUND_TOOL}
          state:
            input: x
"""

TWICE_NESTED_WORKFLOW = f"""
class: GalaxyWorkflow
steps:
  first:{NESTED_LICENSED}
  second:{NESTED_LICENSED}
"""

USER_BOUND_WORKFLOW = f"""
class: GalaxyWorkflow
steps:
  licensed:
    tool_id: {USER_BOUND_TOOL}
    state:
      input: x
"""

PAUSED_WORKFLOW = f"""
class: GalaxyWorkflow
inputs:
  input1: data
steps:
  the_pause:
    type: pause
    in:
      input: input1
  licensed:
    tool_id: {DATA_TOOL}
    in:
      input1: the_pause
"""

PAUSED_USER_BOUND_WORKFLOW = f"""
class: GalaxyWorkflow
inputs:
  input1: data
steps:
  the_pause:
    type: pause
    in:
      input: input1
  licensed:
    tool_id: {USER_BOUND_DATA_TOOL}
    in:
      input1: the_pause
"""


class TestLicenseAcceptanceWorkflows(integration_util.IntegrationTestCase):
    def setUp(self):
        super().setUp()
        self.dataset_populator = DatasetPopulator(self.galaxy_interactor)
        self.workflow_populator = WorkflowPopulator(self.galaxy_interactor)
        self.license_populator = LicenseAgreementsPopulator(self.galaxy_interactor)

    @skip_without_tool(SUBMISSION_BOUND_TOOL)
    def test_invocation_request_rejected_when_license_unaccepted(self):
        with self._fresh_user():
            workflow_id = self.workflow_populator.upload_yaml_workflow(SIMPLE_WORKFLOW)
            history_id = self.dataset_populator.new_history()
            response = self.workflow_populator.invoke_workflow(workflow_id, history_id=history_id)
            self._assert_status_code_is(response, 403)
            error = response.json()
            assert error["err_code"] == 403009
            (unmet,) = error["unmet"]
            assert unmet["kind"] == "license_agreement"
            (agreement,) = unmet["details"]["agreements"]
            assert agreement["id"] == LICENSE_ID
            assert agreement["affirmation"]
            assert [step["path"] for step in agreement["steps"]] == [[1]]
            assert agreement["steps"][0]["tool_id"] == SUBMISSION_BOUND_TOOL
            assert self.workflow_populator.workflow_invocations(workflow_id) == []

    @skip_without_tool(SUBMISSION_BOUND_TOOL)
    def test_subworkflow_license_enforced(self):
        with self._fresh_user():
            workflow_id = self.workflow_populator.upload_yaml_workflow(SUBWORKFLOW_WORKFLOW)
            history_id = self.dataset_populator.new_history()
            response = self.workflow_populator.invoke_workflow(workflow_id, history_id=history_id)
            self._assert_status_code_is(response, 403)
            (unmet,) = response.json()["unmet"]
            (agreement,) = unmet["details"]["agreements"]
            assert [step["path"] for step in agreement["steps"]] == [[1, 1]]

    @skip_without_tool(SUBMISSION_BOUND_TOOL)
    def test_subworkflow_used_twice_reports_and_pins_both(self):
        with self._fresh_user():
            workflow_id = self.workflow_populator.upload_yaml_workflow(TWICE_NESTED_WORKFLOW)
            history_id = self.dataset_populator.new_history()
            response = self.workflow_populator.invoke_workflow(workflow_id, history_id=history_id)
            self._assert_status_code_is(response, 403)
            (unmet,) = response.json()["unmet"]
            (agreement,) = unmet["details"]["agreements"]
            assert [step["path"] for step in agreement["steps"]] == [[0, 0], [1, 0]]

            invocation_id = self._invoke(
                workflow_id, history_id, one_time_license_acceptances=[agreement["agreement_hash"]]
            )
            self.workflow_populator.wait_for_invocation_and_jobs(history_id, workflow_id, invocation_id)
            assert len(self._pinned_invocation_ids()) == 2
            assert len(self._jobs_for_tool(SUBMISSION_BOUND_TOOL)) == 2

    @skip_without_tool(SUBMISSION_BOUND_TOOL)
    def test_run_form_lists_nested_license_agreements_once(self):
        with self._fresh_user():
            workflow_id = self.workflow_populator.upload_yaml_workflow(TWICE_NESTED_WORKFLOW)
            response = self._get(f"workflows/{workflow_id}/download", data={"style": "run"})
            self._assert_status_code_is(response, 200)
            (agreement,) = response.json()["license_agreements"]
            assert agreement["id"] == LICENSE_ID
            assert agreement["terms"]
            assert agreement["accepted"] is False
            assert [step["path"] for step in agreement["steps"]] == [[0, 0], [1, 0]]
            assert {step["tool_id"] for step in agreement["steps"]} == {SUBMISSION_BOUND_TOOL}

    @skip_without_tool(SUBMISSION_BOUND_TOOL)
    def test_workflow_license_agreements_route(self):
        with self._fresh_user():
            workflow_id = self.workflow_populator.upload_yaml_workflow(SUBWORKFLOW_WORKFLOW)
            response = self._get(f"workflows/{workflow_id}/license_agreements")
            self._assert_status_code_is(response, 200)
            (agreement,) = response.json()
            assert agreement["id"] == LICENSE_ID
            assert agreement["accepted"] is False
            assert agreement["steps"] == [{"path": [1, 1], "tool_id": SUBMISSION_BOUND_TOOL, "tool_version": "1.0"}]

    @skip_without_tool(SUBMISSION_BOUND_TOOL)
    def test_one_time_acceptance_persisted_on_invocation_tree(self):
        with self._fresh_user():
            hashes = self.license_populator.license_agreement_hashes(SUBMISSION_BOUND_TOOL)
            workflow_id = self.workflow_populator.upload_yaml_workflow(SUBWORKFLOW_WORKFLOW)
            history_id = self.dataset_populator.new_history()
            invocation_id = self._invoke(workflow_id, history_id, one_time_license_acceptances=hashes)
            self.workflow_populator.wait_for_invocation_and_jobs(history_id, workflow_id, invocation_id)
            invocation = self.workflow_populator.get_invocation(invocation_id)
            assert invocation["state"] in ("scheduled", "completed"), invocation
            (job,) = self._jobs_for_tool(SUBMISSION_BOUND_TOOL)
            (association,) = job.license_acceptance_associations
            assert association.authorization_kind == "one_time"
            # Pinned on the subworkflow invocation that contains the tool, not the outer one.
            pinned = self._pinned_invocation_ids()
            assert len(pinned) == 1
            assert self._app.security.decode_id(invocation_id) not in pinned

    @skip_without_tool(SUBMISSION_BOUND_TOOL)
    @skip_without_tool(USER_BOUND_TOOL)
    def test_one_time_acceptance_not_declared_by_workflow_rejected(self):
        with self._fresh_user():
            other_hashes = self.license_populator.license_agreement_hashes(USER_BOUND_TOOL)
            workflow_id = self.workflow_populator.upload_yaml_workflow(SIMPLE_WORKFLOW)
            history_id = self.dataset_populator.new_history()
            response = self.workflow_populator.invoke_workflow(
                workflow_id, history_id=history_id, request={"one_time_license_acceptances": other_hashes}
            )
            self._assert_status_code_is(response, 400)

    @skip_without_tool(USER_BOUND_TOOL)
    def test_persistent_acceptance_authorizes_invocation(self):
        with self._fresh_user():
            accepted = self.license_populator.accept_license_agreement(USER_BOUND_TOOL, LICENSE_ID)
            workflow_id = self.workflow_populator.upload_yaml_workflow(USER_BOUND_WORKFLOW)
            history_id = self.dataset_populator.new_history()
            invocation_id = self._invoke(workflow_id, history_id)
            self.workflow_populator.wait_for_invocation_and_jobs(history_id, workflow_id, invocation_id)
            (job,) = self._jobs_for_tool(USER_BOUND_TOOL)
            (association,) = job.license_acceptance_associations
            assert association.authorization_kind == "persistent"
            assert association.acceptance_event_id == self._app.security.decode_id(accepted["event"]["id"])

    @skip_without_tool(USER_BOUND_TOOL)
    def test_one_time_workflow_acceptance_does_not_become_user_state(self):
        with self._fresh_user():
            hashes = self.license_populator.license_agreement_hashes(USER_BOUND_TOOL)
            workflow_id = self.workflow_populator.upload_yaml_workflow(USER_BOUND_WORKFLOW)
            history_id = self.dataset_populator.new_history()
            invocation_id = self._invoke(workflow_id, history_id, one_time_license_acceptances=hashes)
            self.workflow_populator.wait_for_invocation_and_jobs(history_id, workflow_id, invocation_id)
            assert self.license_populator.list_license_acceptances(include_history=True)["history"] == []
            response = self.workflow_populator.invoke_workflow(workflow_id, history_id=history_id)
            self._assert_status_code_is(response, 403)

    @skip_without_tool(DATA_TOOL)
    def test_one_time_acceptance_survives_scheduling_delay(self):
        with self._fresh_user():
            hashes = self.license_populator.license_agreement_hashes(DATA_TOOL)
            workflow_id = self.workflow_populator.upload_yaml_workflow(PAUSED_WORKFLOW)
            history_id = self.dataset_populator.new_history()
            hda = self.dataset_populator.new_dataset(history_id, content="a\n", wait=True)
            invocation_id = self._invoke(
                workflow_id,
                history_id,
                inputs={"input1": {"src": "hda", "id": hda["id"]}},
                one_time_license_acceptances=hashes,
            )
            self._wait_for_state(invocation_id, "ready")
            self._resume_pause(invocation_id, order_index=1)
            self.workflow_populator.wait_for_invocation_and_jobs(history_id, workflow_id, invocation_id)
            assert self.workflow_populator.get_invocation(invocation_id)["state"] in ("scheduled", "completed")
            (job,) = self._jobs_for_tool(DATA_TOOL)
            (association,) = job.license_acceptance_associations
            assert association.authorization_kind == "one_time"

    @skip_without_tool(USER_BOUND_DATA_TOOL)
    def test_revoke_between_request_and_schedule_fails_persistently_authorized_invocation(self):
        with self._fresh_user():
            accepted = self.license_populator.accept_license_agreement(USER_BOUND_DATA_TOOL, LICENSE_ID)
            workflow_id = self.workflow_populator.upload_yaml_workflow(PAUSED_USER_BOUND_WORKFLOW)
            history_id = self.dataset_populator.new_history()
            hda = self.dataset_populator.new_dataset(history_id, content="a\n", wait=True)
            invocation_id = self._invoke(workflow_id, history_id, inputs={"input1": {"src": "hda", "id": hda["id"]}})
            self._wait_for_state(invocation_id, "ready")
            self.license_populator.revoke_license_acceptance(accepted["agreement"]["agreement_hash"])
            self._resume_pause(invocation_id, order_index=1)
            self._wait_for_state(invocation_id, "failed")
            (message,) = self.workflow_populator.get_invocation(invocation_id)["messages"]
            assert message["reason"] == "license_not_accepted"
            assert LICENSE_ID in message["details"]
            assert self._jobs_for_tool(USER_BOUND_DATA_TOOL) == []

    @skip_without_tool(USER_BOUND_DATA_TOOL)
    def test_revoke_does_not_invalidate_pinned_one_time_invocation(self):
        with self._fresh_user():
            accepted = self.license_populator.accept_license_agreement(USER_BOUND_DATA_TOOL, LICENSE_ID)
            agreement_hash = accepted["agreement"]["agreement_hash"]
            workflow_id = self.workflow_populator.upload_yaml_workflow(PAUSED_USER_BOUND_WORKFLOW)
            history_id = self.dataset_populator.new_history()
            hda = self.dataset_populator.new_dataset(history_id, content="a\n", wait=True)
            invocation_id = self._invoke(
                workflow_id,
                history_id,
                inputs={"input1": {"src": "hda", "id": hda["id"]}},
                one_time_license_acceptances=[agreement_hash],
            )
            self._wait_for_state(invocation_id, "ready")
            self.license_populator.revoke_license_acceptance(agreement_hash)
            self._resume_pause(invocation_id, order_index=1)
            self.workflow_populator.wait_for_invocation_and_jobs(history_id, workflow_id, invocation_id)
            assert self.workflow_populator.get_invocation(invocation_id)["state"] in ("scheduled", "completed")
            (job,) = self._jobs_for_tool(USER_BOUND_DATA_TOOL)
            (association,) = job.license_acceptance_associations
            assert association.authorization_kind == "one_time"

    @skip_without_tool(DATA_TOOL)
    def test_one_time_acceptance_survives_restart_and_resume(self):
        # restart() reconnects as the default test user, so this runs as that user.
        hashes = self.license_populator.license_agreement_hashes(DATA_TOOL)
        workflow_id = self.workflow_populator.upload_yaml_workflow(PAUSED_WORKFLOW)
        history_id = self.dataset_populator.new_history()
        hda = self.dataset_populator.new_dataset(history_id, content="a\n", wait=True)
        invocation_id = self._invoke(
            workflow_id,
            history_id,
            inputs={"input1": {"src": "hda", "id": hda["id"]}},
            one_time_license_acceptances=hashes,
        )
        self._wait_for_state(invocation_id, "ready")
        self.restart()
        self.setUp()
        self._resume_pause(invocation_id, order_index=1)
        self.workflow_populator.wait_for_invocation_and_jobs(history_id, workflow_id, invocation_id)
        assert self.workflow_populator.get_invocation(invocation_id)["state"] in ("scheduled", "completed")
        jobs = [
            job for job in self._jobs_for_tool(DATA_TOOL) if job.history_id == self._app.security.decode_id(history_id)
        ]
        (job,) = jobs
        (association,) = job.license_acceptance_associations
        assert association.authorization_kind == "one_time"

    def _invoke(self, workflow_id: str, history_id: str, inputs: dict | None = None, **request: Any) -> str:
        response = self.workflow_populator.invoke_workflow(
            workflow_id, history_id=history_id, inputs=inputs, request=request, inputs_by="name"
        )
        self._assert_status_code_is(response, 200)
        return response.json()["id"]

    def _resume_pause(self, invocation_id: str, order_index: int) -> None:
        invocation = self.workflow_populator.get_invocation(invocation_id)
        (pause_step,) = [step for step in invocation["steps"] if step["order_index"] == order_index]
        response = self._put(f"invocations/{invocation_id}/steps/{pause_step['id']}", data={"action": True}, json=True)
        self._assert_status_code_is(response, 200)

    def _wait_for_state(self, invocation_id: str, state: str) -> None:
        for _ in range(60):
            if self.workflow_populator.get_invocation(invocation_id)["state"] == state:
                return
            time.sleep(0.5)
        raise AssertionError(f"Invocation {invocation_id} never reached state [{state}]")

    def _pinned_invocation_ids(self) -> set[int]:
        session = self._app.model.session
        session.expire_all()
        stmt = select(WorkflowInvocationLicenseAcceptanceAssociation.workflow_invocation_id)
        return set(session.scalars(stmt)) & self._current_user_invocation_ids()

    def _current_user_invocation_ids(self) -> set[int]:
        response = self._get("invocations", data={"include_nested_invocations": True})
        return {self._app.security.decode_id(invocation["id"]) for invocation in response.json()}

    def _jobs_for_tool(self, tool_id: str) -> list[Job]:
        session = self._app.model.session
        session.expire_all()
        user_id = self._app.security.decode_id(self._get("users/current").json()["id"])
        stmt = select(Job).where(Job.tool_id == tool_id, Job.user_id == user_id)
        return list(session.scalars(stmt))

    @contextmanager
    def _fresh_user(self):
        with self._different_user(f"{random_name()}@galaxy.org"):
            yield
