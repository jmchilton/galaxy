import pytest
from sqlalchemy import (
    delete,
    select,
)
from sqlalchemy.exc import IntegrityError

from galaxy.model import (
    JobLicenseAcceptanceAssociation,
    ToolLicenseAcceptanceEvent,
    ToolLicenseAgreement,
    User,
    WorkflowInvocationLicenseAcceptanceAssociation,
)
from galaxy.model.db.license_agreement import (
    get_accepted_license_agreements,
    get_latest_license_acceptance_events,
)

HASH_A = "a" * 64
HASH_B = "b" * 64


@pytest.fixture
def make_agreement(session):
    def f(agreement_hash=HASH_A, terms="Terms.", affirmation="I agree."):
        agreement = ToolLicenseAgreement(agreement_hash=agreement_hash, terms=terms, affirmation=affirmation)
        session.add(agreement)
        session.commit()
        return agreement

    return f


@pytest.fixture
def make_event(session):
    def f(user, agreement_hash=HASH_A, action="accept", **kwd):
        event = ToolLicenseAcceptanceEvent(
            user=user, agreement_hash=agreement_hash, action=action, granted_by=kwd.pop("granted_by", "user"), **kwd
        )
        session.add(event)
        session.commit()
        return event

    return f


def test_accept_then_revoke_derives_revoked(session, make_user, make_agreement, make_event):
    user = make_user()
    make_agreement()
    make_event(user, action="accept")
    revoke = make_event(user, action="revoke")

    assert len(session.scalars(select(ToolLicenseAcceptanceEvent)).all()) == 2
    assert get_latest_license_acceptance_events(session, user.id) == {HASH_A: revoke}
    assert get_accepted_license_agreements(session, user.id) == {}


def test_reaccept_after_revoke(session, make_user, make_agreement, make_event):
    user = make_user()
    make_agreement()
    make_event(user, action="accept")
    make_event(user, action="revoke")
    reaccept = make_event(user, action="accept")

    assert len(session.scalars(select(ToolLicenseAcceptanceEvent)).all()) == 3
    assert get_accepted_license_agreements(session, user.id) == {HASH_A: reaccept}


def test_latest_event_per_agreement_and_user(session, make_user, make_agreement, make_event):
    user, other = make_user(), make_user()
    make_agreement(HASH_A)
    make_agreement(HASH_B, terms="Other terms.")
    accept_a = make_event(user, HASH_A, "accept")
    make_event(user, HASH_B, "accept")
    revoke_b = make_event(user, HASH_B, "revoke")
    other_accept_b = make_event(other, HASH_B, "accept")

    assert get_latest_license_acceptance_events(session, user.id) == {HASH_A: accept_a, HASH_B: revoke_b}
    assert get_accepted_license_agreements(session, user.id) == {HASH_A: accept_a}
    assert get_accepted_license_agreements(session, other.id) == {HASH_B: other_accept_b}


def test_event_action_constrained(session, make_user, make_agreement):
    user = make_user()
    make_agreement()
    session.add(ToolLicenseAcceptanceEvent(user=user, agreement_hash=HASH_A, action="bogus", granted_by="user"))
    with pytest.raises(IntegrityError):
        session.commit()


def test_event_granted_by_constrained(session, make_user, make_agreement):
    user = make_user()
    make_agreement()
    session.add(ToolLicenseAcceptanceEvent(user=user, agreement_hash=HASH_A, action="accept", granted_by="bogus"))
    with pytest.raises(IntegrityError):
        session.commit()


def test_event_requires_known_agreement(session, make_user):
    session.add(ToolLicenseAcceptanceEvent(user=make_user(), agreement_hash=HASH_A, action="accept", granted_by="user"))
    with pytest.raises(IntegrityError):
        session.commit()


def test_job_association_pins_event(session, make_user, make_job, make_agreement, make_event):
    user = make_user()
    make_agreement()
    event = make_event(user)
    job = make_job()
    job.license_acceptance_associations.append(
        JobLicenseAcceptanceAssociation(agreement_hash=HASH_A, acceptance_event=event, authorization_kind="persistent")
    )
    session.commit()

    (association,) = job.license_acceptance_associations
    assert association.acceptance_event is event
    assert association.agreement.terms == "Terms."


def test_job_association_one_time_has_no_event(session, make_job, make_agreement):
    make_agreement()
    job = make_job()
    job.license_acceptance_associations.append(
        JobLicenseAcceptanceAssociation(agreement_hash=HASH_A, authorization_kind="one_time")
    )
    session.commit()
    assert job.license_acceptance_associations[0].acceptance_event_id is None


def test_job_association_unique_per_agreement(session, make_job, make_agreement):
    make_agreement()
    job = make_job()
    for _ in range(2):
        job.license_acceptance_associations.append(
            JobLicenseAcceptanceAssociation(agreement_hash=HASH_A, authorization_kind="one_time")
        )
    with pytest.raises(IntegrityError):
        session.commit()


def test_job_association_kind_constrained(session, make_job, make_agreement):
    make_agreement()
    job = make_job()
    job.license_acceptance_associations.append(
        JobLicenseAcceptanceAssociation(agreement_hash=HASH_A, authorization_kind="bogus")
    )
    with pytest.raises(IntegrityError):
        session.commit()


def test_user_deletion_removes_events_but_job_association_keeps_agreement(
    session, make_user, make_job, make_agreement, make_event
):
    user = make_user()
    make_agreement()
    event = make_event(user)
    job = make_job()
    association = JobLicenseAcceptanceAssociation(
        job=job, agreement_hash=HASH_A, acceptance_event=event, authorization_kind="persistent"
    )
    session.add(association)
    session.commit()

    session.execute(delete(User).where(User.id == user.id))
    session.commit()
    session.expire_all()

    assert session.scalars(select(ToolLicenseAcceptanceEvent)).all() == []
    assert association.acceptance_event_id is None
    assert association.authorization_kind == "persistent"
    assert association.agreement.terms == "Terms."


def test_agreement_with_references_cannot_be_deleted(session, make_job, make_agreement):
    make_agreement()
    session.add(JobLicenseAcceptanceAssociation(job=make_job(), agreement_hash=HASH_A, authorization_kind="one_time"))
    session.commit()
    with pytest.raises(IntegrityError):
        session.execute(delete(ToolLicenseAgreement).where(ToolLicenseAgreement.agreement_hash == HASH_A))


def test_workflow_invocation_association(session, make_workflow_invocation, make_agreement):
    make_agreement()
    invocation = make_workflow_invocation()
    invocation.license_acceptance_associations.append(
        WorkflowInvocationLicenseAcceptanceAssociation(agreement_hash=HASH_A)
    )
    session.commit()
    assert invocation.license_acceptance_associations[0].create_time is not None


def test_workflow_invocation_association_unique_per_agreement(session, make_workflow_invocation, make_agreement):
    make_agreement()
    invocation = make_workflow_invocation()
    for _ in range(2):
        invocation.license_acceptance_associations.append(
            WorkflowInvocationLicenseAcceptanceAssociation(agreement_hash=HASH_A)
        )
    with pytest.raises(IntegrityError):
        session.commit()
