import pytest
from sqlalchemy import select

from galaxy import model
from galaxy.exceptions import (
    ItemAccessibilityException,
    ObjectNotFound,
    RequestParameterInvalidException,
)
from galaxy.managers.license_agreements import (
    LicenseAcceptanceManager,
    one_time_hashes_for_invocation,
    validate_one_time_hashes,
)
from galaxy.model import (
    JobLicenseAcceptanceAssociation,
    ToolLicenseAcceptanceEvent,
    ToolLicenseAgreement,
    User,
)
from galaxy.tool_util.license_agreements import (
    resolve_license_agreement,
    ResolvedLicenseAgreement,
)
from galaxy.tool_util_models.tool_source import LicenseAgreement
from .base import BaseTestCase

AFFIRMATION = "I have read and accept the license terms."
TERMS = "Free for academic use."


def resolved(
    id: str = "nc",
    version: str = "1",
    affirmation: str = AFFIRMATION,
    text: str = TERMS,
    binds: str = "user",
    label: str = "Academic use only",
) -> ResolvedLicenseAgreement:
    agreement = LicenseAgreement(id=id, version=version, label=label, affirmation=affirmation, text=text, binds=binds)
    return resolve_license_agreement(agreement, None)


class TestLicenseAcceptanceManager(BaseTestCase):
    def set_up_managers(self):
        super().set_up_managers()
        self.manager = LicenseAcceptanceManager(self.trans.sa_session)

    def test_accept_records_event_and_agreement(self):
        user = self._create_test_user()
        agreement = resolved()
        event = self.manager.accept(user, agreement, prompting_tool_id="tool", prompting_tool_version="1.0")
        assert event.action == ToolLicenseAcceptanceEvent.actions.ACCEPT
        assert event.granted_by == ToolLicenseAcceptanceEvent.granted_by_types.USER
        assert (event.license_id, event.license_version, event.license_label) == ("nc", "1", "Academic use only")
        assert (event.prompting_tool_id, event.prompting_tool_version) == ("tool", "1.0")
        stored = self.trans.sa_session.get(ToolLicenseAgreement, agreement.agreement_hash)
        assert stored is not None
        assert (stored.affirmation, stored.terms) == (AFFIRMATION, TERMS)
        assert self.manager.current_state(user) == {agreement.agreement_hash: event}

    def test_reaccept_after_revoke_records_three_events(self):
        user = self._create_test_user()
        agreement = resolved()
        self.manager.accept(user, agreement)
        self.manager.revoke(user, agreement.agreement_hash)
        assert self.manager.current_state(user) == {}
        reaccept = self.manager.accept(user, agreement)
        history = self.manager.history(user)
        assert [e.action for e in history] == ["accept", "revoke", "accept"]
        assert self.manager.current_state(user) == {agreement.agreement_hash: reaccept}

    def test_describe_reports_persistent_acceptance(self):
        user = self._create_test_user()
        user_bound = resolved()
        submission_bound = resolved(binds="submission", text="Other terms.")
        self.manager.accept(user, user_bound)
        self.manager.accept(user, resolved(text="Other terms."))
        described = self.manager.describe(user, [user_bound, submission_bound])
        assert [(d.id, d.binds, d.accepted) for d in described] == [("nc", "user", True), ("nc", "submission", False)]
        assert described[0].terms == TERMS
        assert described[0].agreement_hash == user_bound.agreement_hash

    def test_describe_for_anonymous_user(self):
        (described,) = self.manager.describe(None, [resolved()])
        assert described.accepted is False

    def test_describe_without_agreements(self):
        assert self.manager.describe(self._create_test_user(), []) == []

    def test_describe_lists_each_agreement_hash_once(self):
        described = self.manager.describe(None, [resolved(id="nc"), resolved(id="academic")])
        assert [d.id for d in described] == ["nc"]

    def test_accept_when_already_accepted_records_no_event(self):
        user = self._create_test_user()
        agreement = resolved()
        first = self.manager.accept(user, agreement)
        assert self.manager.accept(user, agreement) == first
        assert len(self.manager.history(user)) == 1

    def test_revoke_copies_display_metadata(self):
        user = self._create_test_user()
        agreement = resolved()
        self.manager.accept(user, agreement)
        revoke = self.manager.revoke(user, agreement.agreement_hash)
        assert (revoke.license_id, revoke.license_version, revoke.license_label) == ("nc", "1", "Academic use only")

    def test_revoke_without_acceptance_fails(self):
        user = self._create_test_user()
        with pytest.raises(ObjectNotFound):
            self.manager.revoke(user, resolved().agreement_hash)
        assert self.manager.history(user) == []

    def test_persistent_acceptance_of_submission_agreement_rejected(self):
        user = self._create_test_user()
        with pytest.raises(RequestParameterInvalidException):
            self.manager.accept(user, resolved(binds="submission"))
        assert self.manager.history(user) == []

    def test_changed_terms_not_accepted(self):
        user = self._create_test_user()
        self.manager.accept(user, resolved())
        assert self.manager.unmet(user, [resolved(text="Free for academic use only.")]) != []
        assert self.manager.unmet(user, [resolved(affirmation="I accept.")]) != []

    def test_different_ids_identical_agreement_share_acceptance(self):
        user = self._create_test_user()
        self.manager.accept(user, resolved(id="nc"))
        assert self.manager.unmet(user, [resolved(id="academic", version="2", label="Other label")]) == []

    def test_same_id_different_agreement_prompts_twice(self):
        user = self._create_test_user()
        first = resolved(id="nc")
        second = resolved(id="nc", text="Different terms.")
        self.manager.accept(user, first)
        assert self.manager.unmet(user, [first, second]) == [second]

    def test_second_user_reuses_agreement_row(self):
        user1 = self._create_test_user("user1")
        user2 = self._create_test_user("user2")
        agreement = resolved()
        self.manager.accept(user1, agreement)
        self.manager.accept(user2, agreement)
        rows = self.trans.sa_session.scalars(select(ToolLicenseAgreement)).all()
        assert [row.agreement_hash for row in rows] == [agreement.agreement_hash]

    def test_acceptance_is_per_user(self):
        user1 = self._create_test_user("user1")
        user2 = self._create_test_user("user2")
        agreement = resolved()
        self.manager.accept(user1, agreement)
        assert self.manager.unmet(user2, [agreement]) == [agreement]

    def test_unmet_submission_agreement_needs_one_time_acceptance(self):
        user = self._create_test_user()
        agreement = resolved(binds="submission")
        assert self.manager.unmet(user, [agreement]) == [agreement]
        assert self.manager.unmet(user, [agreement], one_time_hashes={agreement.agreement_hash}) == []

    def test_unmet_ignores_persistent_acceptance_once_agreement_binds_submission(self):
        user = self._create_test_user()
        self.manager.accept(user, resolved(binds="user"))
        agreement = resolved(binds="submission")
        assert self.manager.unmet(user, [agreement]) == [agreement]

    def test_unmet_user_agreement_met_by_one_time_acceptance(self):
        user = self._create_test_user()
        agreement = resolved()
        assert self.manager.unmet(user, [agreement], one_time_hashes={agreement.agreement_hash}) == []
        assert self.manager.history(user) == []

    def test_associate_with_job_pins_persistent_event(self):
        user = self._create_test_user()
        agreement = resolved()
        event = self.manager.accept(user, agreement)
        job = self._create_job(user)
        self.manager.associate_with_job(job, self.manager.authorize(user, [agreement]))
        self.trans.sa_session.flush()
        (association,) = job.license_acceptance_associations
        assert association.authorization_kind == JobLicenseAcceptanceAssociation.authorization_kinds.PERSISTENT
        assert association.acceptance_event_id == event.id
        assert association.agreement_hash == agreement.agreement_hash

    def test_associate_with_job_one_time(self):
        user = self._create_test_user()
        agreement = resolved(binds="submission")
        job = self._create_job(user)
        self.manager.associate_with_job(job, self.manager.authorize(user, [agreement], {agreement.agreement_hash}))
        (association,) = job.license_acceptance_associations
        assert association.authorization_kind == JobLicenseAcceptanceAssociation.authorization_kinds.ONE_TIME
        assert association.acceptance_event_id is None
        assert self.trans.sa_session.get(ToolLicenseAgreement, agreement.agreement_hash) is not None
        assert self.manager.history(user) == []

    def test_associate_with_job_unmet_fails(self):
        user = self._create_test_user()
        agreement = resolved()
        job = self._create_job(user)
        with pytest.raises(ItemAccessibilityException):
            self.manager.associate_with_job(job, self.manager.authorize(user, [agreement]))
        assert job.license_acceptance_associations == []

    def test_associate_with_job_different_ids_identical_agreement(self):
        user = self._create_test_user()
        first = resolved(id="nc")
        second = resolved(id="academic")
        self.manager.accept(user, first)
        assert self.manager.unmet(user, [resolved(id="nc", text="Other."), resolved(id="x", text="Other.")]) == [
            resolved(id="nc", text="Other.")
        ]
        job = self._create_job(user)
        self.manager.associate_with_job(job, self.manager.authorize(user, [first, second]))
        self.trans.sa_session.commit()
        assert len(job.license_acceptance_associations) == 1

    def test_associate_with_job_prefers_one_time_acceptance(self):
        user = self._create_test_user()
        agreement = resolved()
        self.manager.accept(user, agreement)
        job = self._create_job(user)
        self.manager.associate_with_job(job, self.manager.authorize(user, [agreement], {agreement.agreement_hash}))
        (association,) = job.license_acceptance_associations
        assert association.authorization_kind == JobLicenseAcceptanceAssociation.authorization_kinds.ONE_TIME
        assert association.acceptance_event_id is None

    def test_authorize_ignores_persistent_acceptance_once_agreement_binds_submission(self):
        user = self._create_test_user()
        self.manager.accept(user, resolved(binds="user"))
        agreement = resolved(binds="submission")
        authorization = self.manager.authorize(user, [agreement])
        assert authorization.unmet == [agreement]
        with pytest.raises(ItemAccessibilityException):
            self.manager.associate_with_job(self._create_job(user), authorization)

    def test_revoke_after_authorize_still_records_authorizing_event(self):
        user = self._create_test_user()
        agreement = resolved()
        event = self.manager.accept(user, agreement)
        authorization = self.manager.authorize(user, [agreement])
        self.manager.revoke(user, agreement.agreement_hash)
        job = self._create_job(user)
        self.manager.associate_with_job(job, authorization)
        self.trans.sa_session.flush()
        (association,) = job.license_acceptance_associations
        assert association.acceptance_event_id == event.id

    def test_anonymous_user_needs_one_time_acceptance(self):
        agreement = resolved()
        assert self.manager.unmet(None, [agreement]) == [agreement]
        assert self.manager.unmet(None, [agreement], {agreement.agreement_hash}) == []

    def test_authorize_without_agreements(self):
        user = self._create_test_user()
        authorization = self.manager.authorize(user, [])
        assert (authorization.one_time, authorization.persistent, authorization.unmet) == ([], [], [])

    def test_validate_one_time_hashes_rejects_undeclared_agreement(self):
        declared = resolved()
        other = resolved(text="Other terms.")
        assert validate_one_time_hashes([declared], [declared.agreement_hash]) == {declared.agreement_hash}
        with pytest.raises(RequestParameterInvalidException, match=other.agreement_hash):
            validate_one_time_hashes([declared], [declared.agreement_hash, other.agreement_hash])

    def test_one_time_hashes_for_invocation(self):
        agreement = resolved(binds="submission")
        invocation = model.WorkflowInvocation()
        invocation.workflow = model.Workflow()
        self.trans.sa_session.add(invocation)
        assert one_time_hashes_for_invocation(invocation) == set()
        self.manager.ensure_agreement(agreement)
        self.manager.associate_one_time_with_invocation(invocation, [agreement.agreement_hash])
        self.trans.sa_session.commit()
        assert one_time_hashes_for_invocation(invocation) == {agreement.agreement_hash}

    def test_associate_one_time_with_invocation(self):
        user = self._create_test_user()
        agreement = resolved(binds="submission")
        invocation = model.WorkflowInvocation()
        invocation.workflow = model.Workflow()
        self.trans.sa_session.add(invocation)
        self.manager.ensure_agreement(agreement)
        self.manager.associate_one_time_with_invocation(invocation, [agreement.agreement_hash])
        self.trans.sa_session.commit()
        (association,) = invocation.license_acceptance_associations
        assert association.agreement_hash == agreement.agreement_hash
        assert association.agreement.terms == TERMS
        assert self.manager.history(user) == []

    def test_associate_one_time_with_invocation_pins_each_agreement_once(self):
        agreement = resolved(binds="submission")
        invocation = model.WorkflowInvocation()
        invocation.workflow = model.Workflow()
        self.trans.sa_session.add(invocation)
        self.manager.ensure_agreement(agreement)
        self.manager.associate_one_time_with_invocation(invocation, [agreement.agreement_hash] * 2)
        self.manager.associate_one_time_with_invocation(invocation, [agreement.agreement_hash])
        self.trans.sa_session.commit()
        assert len(invocation.license_acceptance_associations) == 1

    def test_user_purge_removes_events_but_job_association_resolves_terms(self):
        self.trans.app.config.allow_user_deletion = True
        user = self._create_test_user()
        agreement = resolved()
        self.manager.accept(user, agreement)
        job = self._create_job(user)
        self.manager.associate_with_job(job, self.manager.authorize(user, [agreement]))
        self.trans.sa_session.commit()

        self.user_manager.delete(user)
        self.user_manager.purge(user)
        self.trans.sa_session.commit()

        assert self.manager.history(user) == []
        self.trans.sa_session.refresh(job)
        (association,) = job.license_acceptance_associations
        assert association.acceptance_event_id is None
        assert association.authorization_kind == JobLicenseAcceptanceAssociation.authorization_kinds.PERSISTENT
        assert association.agreement.terms == TERMS

    def test_user_purge_keeps_events_granted_by_them_for_others(self):
        self.trans.app.config.allow_user_deletion = True
        granter = self._create_test_user("granter")
        user = self._create_test_user("user")
        agreement = resolved()
        event = self.manager.accept(
            user, agreement, granted_by=ToolLicenseAcceptanceEvent.granted_by_types.ADMIN, granted_by_user=granter
        )
        self.trans.sa_session.commit()

        self.user_manager.delete(granter)
        self.user_manager.purge(granter)
        self.trans.sa_session.commit()

        self.trans.sa_session.refresh(event)
        assert event.granted_by_user_id is None
        assert self.manager.current_state(user) == {agreement.agreement_hash: event}

    def _create_job(self, user: User) -> model.Job:
        job = model.Job()
        job.user = user
        job.tool_id = "license_tool"
        self.trans.sa_session.add(job)
        self.trans.sa_session.commit()
        return job

    def _create_test_user(self, username="user1") -> User:
        user_data = dict(email=f"{username}@user.email", username=username, password="password")
        return self.user_manager.create(**user_data)
