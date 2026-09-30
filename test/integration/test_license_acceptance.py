from contextlib import contextmanager
from typing import Any

from sqlalchemy import select

from galaxy.model import (
    Job,
    JobLicenseAcceptanceAssociation,
)
from galaxy_test.base.api_util import random_name
from galaxy_test.base.populators import (
    DatasetCollectionPopulator,
    DatasetPopulator,
    LicenseAgreementsPopulator,
    skip_without_tool,
)
from galaxy_test.driver import integration_util

USER_BOUND_TOOL = "license_agreement_variant_tool"
SUBMISSION_BOUND_TOOL = "license_agreement_path_tool"
MULTI_TOOL = "license_agreement_multi_tool"
DATA_TOOL = "license_agreement_data_tool"
UNLICENSED_TOOL = "cat1"
LICENSE_ID = "license_agreement_path"


class TestLicenseAcceptanceEnforcement(integration_util.IntegrationTestCase):
    def setUp(self):
        super().setUp()
        self.dataset_populator = DatasetPopulator(self.galaxy_interactor)
        self.dataset_collection_populator = DatasetCollectionPopulator(self.galaxy_interactor)
        self.license_populator = LicenseAgreementsPopulator(self.galaxy_interactor)

    @skip_without_tool(SUBMISSION_BOUND_TOOL)
    def test_tool_execution_blocked_without_license_acceptance(self):
        with self._fresh_user():
            history_id = self.dataset_populator.new_history()
            response = self.dataset_populator.run_tool_raw(SUBMISSION_BOUND_TOOL, {"input": "x"}, history_id)
            self._assert_status_code_is(response, 403)
            error = response.json()
            assert error["err_code"] == 403009
            (unmet,) = error["unmet"]
            assert unmet["kind"] == "license_agreement"
            (agreement,) = unmet["details"]["agreements"]
            assert agreement["id"] == LICENSE_ID
            assert (
                agreement["agreement_hash"] == self.license_populator.license_agreement_hashes(SUBMISSION_BOUND_TOOL)[0]
            )
            assert self._jobs_for_tool(SUBMISSION_BOUND_TOOL) == []

    @skip_without_tool(USER_BOUND_TOOL)
    def test_execution_allowed_after_acceptance(self):
        with self._fresh_user():
            accepted = self.license_populator.accept_license_agreement(USER_BOUND_TOOL, LICENSE_ID)
            job_id = self._run(USER_BOUND_TOOL)
            (association,) = self._job_associations(job_id)
            assert association.authorization_kind == "persistent"
            assert association.acceptance_event_id == self._app.security.decode_id(accepted["event"]["id"])
            assert association.agreement_hash == accepted["agreement"]["agreement_hash"]

    @skip_without_tool(SUBMISSION_BOUND_TOOL)
    def test_execution_allowed_with_one_time_acceptance(self):
        with self._fresh_user():
            hashes = self.license_populator.license_agreement_hashes(SUBMISSION_BOUND_TOOL)
            job_id = self._run(SUBMISSION_BOUND_TOOL, one_time_license_acceptances=hashes)
            (association,) = self._job_associations(job_id)
            assert association.authorization_kind == "one_time"
            assert association.acceptance_event_id is None
            assert association.agreement_hash == hashes[0]
            assert self.license_populator.list_license_acceptances(include_history=True)["history"] == []

            # The next submission prompts again.
            history_id = self.dataset_populator.new_history()
            response = self.dataset_populator.run_tool_raw(SUBMISSION_BOUND_TOOL, {"input": "x"}, history_id)
            self._assert_status_code_is(response, 403)

    @skip_without_tool(MULTI_TOOL)
    def test_one_time_acceptance_must_cover_every_agreement(self):
        with self._fresh_user():
            first, second = self.license_populator.license_agreement_hashes(MULTI_TOOL)
            history_id = self.dataset_populator.new_history()
            response = self.dataset_populator.run_tool_raw(
                MULTI_TOOL, {"input": "x"}, history_id, one_time_license_acceptances=[first]
            )
            self._assert_status_code_is(response, 403)
            (unmet,) = response.json()["unmet"]
            assert [a["agreement_hash"] for a in unmet["details"]["agreements"]] == [second]
            job_id = self._run(MULTI_TOOL, one_time_license_acceptances=[first, second])
            assert len(self._job_associations(job_id)) == 2

    @skip_without_tool(SUBMISSION_BOUND_TOOL)
    @skip_without_tool(USER_BOUND_TOOL)
    def test_one_time_acceptance_for_another_tool_rejected(self):
        with self._fresh_user():
            other_hashes = self.license_populator.license_agreement_hashes(USER_BOUND_TOOL)
            history_id = self.dataset_populator.new_history()
            response = self.dataset_populator.run_tool_raw(
                SUBMISSION_BOUND_TOOL, {"input": "x"}, history_id, one_time_license_acceptances=other_hashes
            )
            self._assert_status_code_is(response, 400)
            assert self._jobs_for_tool(SUBMISSION_BOUND_TOOL) == []

    @skip_without_tool(USER_BOUND_TOOL)
    def test_execution_blocked_after_revoke(self):
        with self._fresh_user():
            accepted = self.license_populator.accept_license_agreement(USER_BOUND_TOOL, LICENSE_ID)
            self.license_populator.revoke_license_acceptance(accepted["agreement"]["agreement_hash"])
            history_id = self.dataset_populator.new_history()
            response = self.dataset_populator.run_tool_raw(USER_BOUND_TOOL, {"input": "x"}, history_id)
            self._assert_status_code_is(response, 403)

    @skip_without_tool(USER_BOUND_TOOL)
    def test_revoke_does_not_affect_completed_job(self):
        with self._fresh_user():
            accepted = self.license_populator.accept_license_agreement(USER_BOUND_TOOL, LICENSE_ID)
            job_id = self._run(USER_BOUND_TOOL, wait=True)
            self.license_populator.revoke_license_acceptance(accepted["agreement"]["agreement_hash"])
            assert self.dataset_populator.get_job_details(job_id).json()["state"] == "ok"
            (association,) = self._job_associations(job_id)
            assert association.acceptance_event_id is not None

    @skip_without_tool(DATA_TOOL)
    def test_blocked_map_over_creates_no_outputs(self):
        with self._fresh_user():
            history_id = self.dataset_populator.new_history()
            hdca_id = self._list_of_two(history_id)
            collections_before = self._collection_ids(history_id)
            response = self.dataset_populator.run_tool_raw(DATA_TOOL, self._map_over(hdca_id), history_id)
            self._assert_status_code_is(response, 403)
            assert self._collection_ids(history_id) == collections_before
            assert self._jobs_for_tool(DATA_TOOL) == []

    @skip_without_tool(DATA_TOOL)
    def test_one_time_acceptance_covers_every_mapped_job(self):
        with self._fresh_user():
            hashes = self.license_populator.license_agreement_hashes(DATA_TOOL)
            history_id = self.dataset_populator.new_history()
            hdca_id = self._list_of_two(history_id)
            response = self.dataset_populator.run_tool(
                DATA_TOOL, self._map_over(hdca_id), history_id, one_time_license_acceptances=hashes
            )
            assert len(response["jobs"]) == 2
            for job in response["jobs"]:
                (association,) = self._job_associations(job["id"])
                assert association.authorization_kind == "one_time"

    @skip_without_tool(UNLICENSED_TOOL)
    def test_one_time_acceptance_on_unlicensed_tool_rejected(self):
        with self._fresh_user():
            history_id = self.dataset_populator.new_history()
            hda = self.dataset_populator.new_dataset(history_id, wait=True)
            response = self.dataset_populator.run_tool_raw(
                UNLICENSED_TOOL,
                {"input1": {"src": "hda", "id": hda["id"]}},
                history_id,
                one_time_license_acceptances=["a" * 64],
            )
            self._assert_status_code_is(response, 400)

    @skip_without_tool(SUBMISSION_BOUND_TOOL)
    def test_async_tool_request_fails_without_license_acceptance(self):
        with self._fresh_user():
            history_id = self.dataset_populator.new_history()
            response = self.dataset_populator.tool_request_raw(SUBMISSION_BOUND_TOOL, {"input": "x"}, history_id)
            self._assert_status_code_is(response, 200)
            tool_request_id = response.json()["tool_request_id"]
            assert not self.dataset_populator.wait_on_tool_request(tool_request_id)
            state_message = self.dataset_populator.get_tool_request(tool_request_id)["state_message"]
            assert state_message["err_code"] == 403009
            (unmet,) = state_message["unmet"]
            assert unmet["kind"] == "license_agreement"
            assert self._jobs_for_tool(SUBMISSION_BOUND_TOOL) == []

    @skip_without_tool(SUBMISSION_BOUND_TOOL)
    def test_async_tool_request_with_one_time_acceptance(self):
        with self._fresh_user():
            hashes = self.license_populator.license_agreement_hashes(SUBMISSION_BOUND_TOOL)
            history_id = self.dataset_populator.new_history()
            response = self.dataset_populator.tool_request_raw(
                SUBMISSION_BOUND_TOOL, {"input": "x"}, history_id, one_time_license_acceptances=hashes
            )
            self._assert_status_code_is(response, 200)
            assert self.dataset_populator.wait_on_tool_request(response.json()["tool_request_id"])
            (job,) = self._jobs_for_tool(SUBMISSION_BOUND_TOOL)
            (association,) = job.license_acceptance_associations
            assert association.authorization_kind == "one_time"

    @skip_without_tool(SUBMISSION_BOUND_TOOL)
    @skip_without_tool(USER_BOUND_TOOL)
    def test_async_tool_request_for_another_tools_hash_rejected(self):
        with self._fresh_user():
            other_hashes = self.license_populator.license_agreement_hashes(USER_BOUND_TOOL)
            history_id = self.dataset_populator.new_history()
            response = self.dataset_populator.tool_request_raw(
                SUBMISSION_BOUND_TOOL, {"input": "x"}, history_id, one_time_license_acceptances=other_hashes
            )
            self._assert_status_code_is(response, 400)

    @skip_without_tool(SUBMISSION_BOUND_TOOL)
    def test_anonymous_tool_run_requires_login(self):
        history_id = self.dataset_populator.new_history()
        payload = {"tool_id": SUBMISSION_BOUND_TOOL, "history_id": history_id, "inputs": {"input": "x"}}
        response = self._post("jobs", data=payload, json=True, anon=True)
        self._assert_status_code_is(response, 403)
        error = response.json()
        assert error["err_code"] == 403009
        (unmet,) = error["unmet"]
        assert unmet["kind"] == "access"
        assert unmet["remedy_route"] == "/login/start"

    @skip_without_tool(UNLICENSED_TOOL)
    def test_failed_tool_request_records_error_code(self):
        history_id = self.dataset_populator.new_history()
        inputs = {"input1": {"src": "url", "url": "http://127.0.0.1:1/missing.txt", "ext": "txt"}}
        response = self.dataset_populator.tool_request_raw(UNLICENSED_TOOL, inputs, history_id)
        self._assert_status_code_is(response, 200)
        tool_request_id = response.json()["tool_request_id"]
        assert not self.dataset_populator.wait_on_tool_request(tool_request_id)
        state_message = self.dataset_populator.get_tool_request(tool_request_id)["state_message"]
        assert isinstance(state_message["err_code"], int)
        assert state_message["err_code"] != 403009
        assert state_message.get("unmet") is None

    def _run(self, tool_id: str, wait: bool = False, **kwds: Any) -> str:
        history_id = self.dataset_populator.new_history()
        response = self.dataset_populator.run_tool(tool_id, {"input": "x"}, history_id, **kwds)
        job_id = response["jobs"][0]["id"]
        if wait:
            self.dataset_populator.wait_for_job(job_id, assert_ok=True)
        return job_id

    def _list_of_two(self, history_id: str) -> str:
        return self.dataset_collection_populator.create_list_in_history(
            history_id, contents=["a\n", "b\n"], wait=True
        ).json()["outputs"][0]["id"]

    def _map_over(self, hdca_id: str) -> dict[str, Any]:
        return {"input1": {"batch": True, "values": [{"src": "hdca", "id": hdca_id}]}}

    def _collection_ids(self, history_id: str) -> list[str]:
        contents = self.dataset_populator.get_history_contents_of_type(history_id, "dataset_collections")
        return sorted(item["id"] for item in contents)

    def _job_associations(self, job_id: str) -> list[JobLicenseAcceptanceAssociation]:
        session = self._app.model.session
        session.expire_all()
        stmt = select(JobLicenseAcceptanceAssociation).where(
            JobLicenseAcceptanceAssociation.job_id == self._app.security.decode_id(job_id)
        )
        return list(session.scalars(stmt))

    def _jobs_for_tool(self, tool_id: str) -> list[Job]:
        session = self._app.model.session
        session.expire_all()
        stmt = select(Job).where(Job.tool_id == tool_id, Job.user_id == self._current_user_id())
        return list(session.scalars(stmt))

    def _current_user_id(self) -> int:
        return self._app.security.decode_id(self._get("users/current").json()["id"])

    @contextmanager
    def _fresh_user(self):
        with self._different_user(f"{random_name()}@galaxy.org"):
            yield
