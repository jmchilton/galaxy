from contextlib import contextmanager

from galaxy_test.base.api_util import random_name
from galaxy_test.base.populators import (
    LicenseAgreementsPopulator,
    skip_without_tool,
)
from ._framework import ApiTestCase

USER_BOUND_TOOL = "license_agreement_variant_tool"
SUBMISSION_BOUND_TOOL = "license_agreement_path_tool"
MULTI_TOOL = "license_agreement_multi_tool"
LICENSE_ID = "license_agreement_path"


class TestLicenseAgreementsApi(ApiTestCase):
    def setUp(self):
        super().setUp()
        self.license_populator = LicenseAgreementsPopulator(self.galaxy_interactor)

    @skip_without_tool(MULTI_TOOL)
    def test_tool_license_agreements(self):
        agreements = self.license_populator.tool_license_agreements(MULTI_TOOL)
        assert [a["id"] for a in agreements] == ["license_agreement_inline", LICENSE_ID]
        for agreement in agreements:
            assert len(agreement["agreement_hash"]) == 64
            assert agreement["terms"]
            assert agreement["affirmation"]
            assert agreement["binds"] == "submission"
            assert agreement["accepted"] is False

    @skip_without_tool(MULTI_TOOL)
    def test_tool_license_agreements_unknown_version(self):
        self.license_populator.tool_license_agreements(MULTI_TOOL, tool_version="99.0", expected_status=404)

    def test_tool_license_agreements_unknown_tool(self):
        self.license_populator.tool_license_agreements("not_a_license_tool", expected_status=404)

    @skip_without_tool(USER_BOUND_TOOL)
    def test_accept_and_revoke(self):
        with self._fresh_user():
            (agreement_hash,) = self.license_populator.license_agreement_hashes(USER_BOUND_TOOL)
            accepted = self.license_populator.accept_license_agreement(USER_BOUND_TOOL, LICENSE_ID)
            assert accepted["agreement"]["agreement_hash"] == agreement_hash
            assert accepted["event"]["action"] == "accept"
            assert accepted["event"]["license_id"] == LICENSE_ID
            assert accepted["event"]["prompting_tool_id"] == USER_BOUND_TOOL
            (agreement,) = self.license_populator.tool_license_agreements(USER_BOUND_TOOL)
            assert agreement["accepted"] is True
            state = self.license_populator.list_license_acceptances()
            assert [a["agreement"]["agreement_hash"] for a in state["accepted"]] == [agreement_hash]
            assert state["history"] is None

            self.license_populator.revoke_license_acceptance(agreement_hash)
            assert self.license_populator.list_license_acceptances()["accepted"] == []
            (agreement,) = self.license_populator.tool_license_agreements(USER_BOUND_TOOL)
            assert agreement["accepted"] is False

    @skip_without_tool(USER_BOUND_TOOL)
    def test_accept_with_undisplayed_hash_rejected(self):
        with self._fresh_user():
            self.license_populator.accept_license_agreement(
                USER_BOUND_TOOL, LICENSE_ID, agreement_hash="b" * 64, expected_status=400
            )
            assert self.license_populator.list_license_acceptances(include_history=True)["history"] == []

    @skip_without_tool(MULTI_TOOL)
    def test_anonymous_tool_license_agreements_requires_login(self):
        response = self._get(f"tools/{MULTI_TOOL}/license_agreements", anon=True)
        self._assert_status_code_is(response, 403)
        error = response.json()
        assert error["err_code"] == 403009
        assert error["unmet"][0]["remedy_route"] == "/login/start"

    def test_tool_license_agreements_accepts_tool_shed_ids(self):
        tool_id = "toolshed.example.org/repos/owner/repo/license_tool/1.0"
        response = self._get(f"tools/{tool_id}/license_agreements")
        self._assert_status_code_is(response, 404)
        assert tool_id in response.json()["err_msg"]

    @skip_without_tool(USER_BOUND_TOOL)
    def test_history_ordering(self):
        with self._fresh_user():
            (agreement_hash,) = self.license_populator.license_agreement_hashes(USER_BOUND_TOOL)
            self.license_populator.accept_license_agreement(USER_BOUND_TOOL, LICENSE_ID)
            self.license_populator.revoke_license_acceptance(agreement_hash)
            self.license_populator.accept_license_agreement(USER_BOUND_TOOL, LICENSE_ID)
            history = self.license_populator.list_license_acceptances(include_history=True)["history"]
            assert [event["action"] for event in history] == ["accept", "revoke", "accept"]
            assert {event["agreement_hash"] for event in history} == {agreement_hash}

    @skip_without_tool(SUBMISSION_BOUND_TOOL)
    def test_persistent_acceptance_of_submission_agreement_rejected(self):
        with self._fresh_user():
            self.license_populator.accept_license_agreement(SUBMISSION_BOUND_TOOL, LICENSE_ID, expected_status=400)
            assert self.license_populator.list_license_acceptances(include_history=True)["history"] == []

    @skip_without_tool(USER_BOUND_TOOL)
    def test_accept_unknown_license_id_rejected(self):
        with self._fresh_user():
            self.license_populator.accept_license_agreement(USER_BOUND_TOOL, "not_declared", expected_status=400)
            assert self.license_populator.list_license_acceptances(include_history=True)["history"] == []

    def test_accept_unknown_tool_rejected(self):
        with self._fresh_user():
            self.license_populator.accept_license_agreement("not_a_license_tool", LICENSE_ID, expected_status=400)
            assert self.license_populator.list_license_acceptances(include_history=True)["history"] == []

    def test_revoke_unaccepted_agreement(self):
        with self._fresh_user():
            self.license_populator.revoke_license_acceptance("a" * 64, expected_status=404)

    @skip_without_tool(USER_BOUND_TOOL)
    def test_acceptance_is_per_user(self):
        with self._fresh_user():
            self.license_populator.accept_license_agreement(USER_BOUND_TOOL, LICENSE_ID)
        with self._fresh_user():
            assert self.license_populator.list_license_acceptances()["accepted"] == []

    def test_other_users_acceptances_forbidden(self):
        other_user_id = self._setup_user(f"{random_name()}@galaxy.org")["id"]
        response = self._get(f"users/{other_user_id}/license_acceptances")
        self._assert_status_code_is(response, 403)

    @skip_without_tool(USER_BOUND_TOOL)
    def test_anonymous_cannot_accept(self):
        payload = {"tool_id": USER_BOUND_TOOL, "license_id": LICENSE_ID, "agreement_hash": "0" * 64}
        response = self._post("users/current/license_acceptances", data=payload, json=True, anon=True)
        self._assert_status_code_is(response, 403)
        response = self._get("users/current/license_acceptances", anon=True)
        self._assert_status_code_is(response, 403)

    @contextmanager
    def _fresh_user(self):
        with self._different_user(f"{random_name()}@galaxy.org"):
            yield
