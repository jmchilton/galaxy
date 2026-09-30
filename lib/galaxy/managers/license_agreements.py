"""Record and check user acceptance of tool license agreements."""

import logging
from collections.abc import (
    Collection,
    Iterable,
)
from dataclasses import (
    dataclass,
    field,
)

from sqlalchemy import (
    delete,
    select,
    update,
)
from sqlalchemy.exc import IntegrityError

from galaxy.exceptions import (
    ItemAccessibilityException,
    ObjectNotFound,
    RequestParameterInvalidException,
)
from galaxy.model import (
    Job,
    JobLicenseAcceptanceAssociation,
    ToolLicenseAcceptanceEvent,
    ToolLicenseAgreement,
    User,
    WorkflowInvocation,
    WorkflowInvocationLicenseAcceptanceAssociation,
)
from galaxy.model.db.license_agreement import get_accepted_license_agreements
from galaxy.model.scoped_session import galaxy_scoped_session
from galaxy.tool_util.license_agreements import ResolvedLicenseAgreement

log = logging.getLogger(__name__)


@dataclass
class LicenseAgreementAuthorization:
    """How each of a submission's license agreements is authorized, one entry per agreement hash."""

    one_time: list[ResolvedLicenseAgreement] = field(default_factory=list)
    persistent: list[ToolLicenseAcceptanceEvent] = field(default_factory=list)
    unmet: list[ResolvedLicenseAgreement] = field(default_factory=list)


class LicenseAcceptanceManager:
    """Persistent (per user) and one-time (per submission) acceptance of tool license agreements.

    Persistent state is derived from the newest acceptance event per agreement and is only
    honoured for ``binds="user"`` agreements. Callers own the transaction - methods never commit.
    """

    def __init__(self, session: galaxy_scoped_session) -> None:
        self.session = session

    def ensure_agreement(self, agreement: ResolvedLicenseAgreement) -> ToolLicenseAgreement:
        """Return the stored terms for ``agreement``, inserting them the first time they are seen."""
        existing = self.session.get(ToolLicenseAgreement, agreement.agreement_hash)
        if existing is not None:
            return existing
        stored = ToolLicenseAgreement(
            agreement_hash=agreement.agreement_hash,
            affirmation=agreement.agreement.affirmation,
            terms=agreement.terms,
        )
        try:
            with self.session.begin_nested():
                self.session.add(stored)
                self.session.flush()
        except IntegrityError:
            # A concurrent writer stored the same content-addressed row; the savepoint only undid our insert.
            winner = self.session.get(ToolLicenseAgreement, agreement.agreement_hash)
            if winner is None:
                raise
            return winner
        return stored

    def current_state(self, user: User) -> dict[str, ToolLicenseAcceptanceEvent]:
        """Agreement hashes the user currently accepts, mapped to the accepting event."""
        return get_accepted_license_agreements(self.session, user.id)

    def history(self, user: User) -> list[ToolLicenseAcceptanceEvent]:
        """Every acceptance and revocation by the user, oldest first."""
        stmt = (
            select(ToolLicenseAcceptanceEvent)
            .where(ToolLicenseAcceptanceEvent.user_id == user.id)
            .order_by(ToolLicenseAcceptanceEvent.id)
        )
        return list(self.session.scalars(stmt))

    def accept(
        self,
        user: User,
        agreement: ResolvedLicenseAgreement,
        prompting_tool_id: str | None = None,
        prompting_tool_version: str | None = None,
        granted_by: ToolLicenseAcceptanceEvent.granted_by_types = ToolLicenseAcceptanceEvent.granted_by_types.USER,
        granted_by_user: User | None = None,
    ) -> ToolLicenseAcceptanceEvent:
        """Persistently accept ``agreement`` for ``user``; already accepted agreements return the accepting event."""
        declared = agreement.agreement
        if declared.binds != "user":
            raise RequestParameterInvalidException(
                f"License agreement [{declared.id}] is a statement about each submission and cannot be accepted "
                "persistently - accept it once per submission instead."
            )
        accepted = self.current_state(user).get(agreement.agreement_hash)
        if accepted is not None:
            return accepted
        self.ensure_agreement(agreement)
        event = ToolLicenseAcceptanceEvent(
            user=user,
            agreement_hash=agreement.agreement_hash,
            action=ToolLicenseAcceptanceEvent.actions.ACCEPT,
            license_id=declared.id,
            license_version=declared.version,
            license_label=declared.label,
            license_url=declared.url,
            granted_by=granted_by,
            granted_by_user=granted_by_user,
            prompting_tool_id=prompting_tool_id,
            prompting_tool_version=prompting_tool_version,
        )
        self.session.add(event)
        self.session.flush()
        return event

    def revoke(self, user: User, agreement_hash: str) -> ToolLicenseAcceptanceEvent:
        """Revoke a persistent acceptance, carrying the accepting event's display metadata onto the revocation."""
        accepted = self.current_state(user).get(agreement_hash)
        if accepted is None:
            raise ObjectNotFound(f"License agreement [{agreement_hash}] is not currently accepted.")
        event = ToolLicenseAcceptanceEvent(
            user=user,
            agreement_hash=agreement_hash,
            action=ToolLicenseAcceptanceEvent.actions.REVOKE,
            license_id=accepted.license_id,
            license_version=accepted.license_version,
            license_label=accepted.license_label,
            license_url=accepted.license_url,
            granted_by=ToolLicenseAcceptanceEvent.granted_by_types.USER,
        )
        self.session.add(event)
        self.session.flush()
        return event

    def unmet(
        self,
        user: User | None,
        agreements: Iterable[ResolvedLicenseAgreement],
        one_time_hashes: Collection[str] = (),
    ) -> list[ResolvedLicenseAgreement]:
        """Agreements neither accepted for this submission (``one_time_hashes``) nor persistently accepted."""
        return self._resolve(user, agreements, one_time_hashes).unmet

    def authorize(
        self,
        user: User | None,
        agreements: Iterable[ResolvedLicenseAgreement],
        one_time_hashes: Collection[str] = (),
    ) -> LicenseAgreementAuthorization:
        """Resolve once per submission how each agreement is authorized, storing one-time terms.

        The result is recorded on each resulting job with ``associate_with_job``, so a revocation
        between checking and job creation cannot leave a job without its authorization.
        """
        authorization = self._resolve(user, agreements, one_time_hashes)
        for agreement in authorization.one_time:
            self.ensure_agreement(agreement)
        return authorization

    def associate_with_job(self, job: Job, authorization: LicenseAgreementAuthorization) -> None:
        """Record on ``job`` the acceptance each agreement was authorized by. Does not flush."""
        if authorization.unmet:
            ids = ", ".join(agreement.agreement.id for agreement in authorization.unmet)
            raise ItemAccessibilityException(f"License agreements [{ids}] have not been accepted.")
        for agreement in authorization.one_time:
            job.license_acceptance_associations.append(
                JobLicenseAcceptanceAssociation(
                    agreement_hash=agreement.agreement_hash,
                    authorization_kind=JobLicenseAcceptanceAssociation.authorization_kinds.ONE_TIME,
                )
            )
        for event in authorization.persistent:
            job.license_acceptance_associations.append(
                JobLicenseAcceptanceAssociation(
                    agreement_hash=event.agreement_hash,
                    authorization_kind=JobLicenseAcceptanceAssociation.authorization_kinds.PERSISTENT,
                    acceptance_event=event,
                )
            )

    def associate_one_time_with_invocation(
        self, invocation: WorkflowInvocation, agreements: Iterable[ResolvedLicenseAgreement]
    ) -> None:
        """Pin one-time acceptances to ``invocation`` so they authorize its jobs for its whole lifetime."""
        pinned = one_time_hashes_for_invocation(invocation)
        for agreement in _unique(agreements):
            if agreement.agreement_hash in pinned:
                continue
            self.ensure_agreement(agreement)
            invocation.license_acceptance_associations.append(
                WorkflowInvocationLicenseAcceptanceAssociation(agreement_hash=agreement.agreement_hash)
            )

    def purge_user(self, user: User) -> None:
        """Remove a purged user's personal acceptance events.

        Jobs keep their association - agreement hash and authorization kind - with the event
        reference cleared. Events the user granted on behalf of others are kept, unattributed.
        """
        event_ids = select(ToolLicenseAcceptanceEvent.id).where(ToolLicenseAcceptanceEvent.user_id == user.id)
        self.session.execute(
            update(JobLicenseAcceptanceAssociation)
            .where(JobLicenseAcceptanceAssociation.acceptance_event_id.in_(event_ids.scalar_subquery()))
            .values(acceptance_event_id=None),
            execution_options={"synchronize_session": False},
        )
        self.session.execute(
            update(ToolLicenseAcceptanceEvent)
            .where(ToolLicenseAcceptanceEvent.granted_by_user_id == user.id)
            .values(granted_by_user_id=None),
            execution_options={"synchronize_session": False},
        )
        self.session.execute(
            delete(ToolLicenseAcceptanceEvent).where(ToolLicenseAcceptanceEvent.user_id == user.id),
            execution_options={"synchronize_session": False},
        )

    def _resolve(
        self,
        user: User | None,
        agreements: Iterable[ResolvedLicenseAgreement],
        one_time_hashes: Collection[str],
    ) -> LicenseAgreementAuthorization:
        agreements = _unique(agreements)
        if not agreements:
            return LicenseAgreementAuthorization()
        accepted = self.current_state(user) if user is not None else {}
        authorization = LicenseAgreementAuthorization()
        for agreement in agreements:
            # A one-time acceptance records what the user affirmed for this submission, so it wins.
            if agreement.agreement_hash in one_time_hashes:
                authorization.one_time.append(agreement)
            elif agreement.agreement.binds == "user" and agreement.agreement_hash in accepted:
                authorization.persistent.append(accepted[agreement.agreement_hash])
            else:
                authorization.unmet.append(agreement)
        return authorization


def validate_one_time_hashes(declared: Iterable[ResolvedLicenseAgreement], one_time_hashes: Iterable[str]) -> set[str]:
    """Reject one-time acceptances of agreements the submitted tool or workflow does not declare."""
    hashes = set(one_time_hashes)
    undeclared = hashes - {agreement.agreement_hash for agreement in declared}
    if undeclared:
        raise RequestParameterInvalidException(
            f"One-time license acceptances [{', '.join(sorted(undeclared))}] are not declared by the submitted tools."
        )
    return hashes


def one_time_hashes_for_invocation(invocation: WorkflowInvocation) -> set[str]:
    """Agreement hashes accepted one-time for ``invocation``."""
    return {association.agreement_hash for association in invocation.license_acceptance_associations}


def _unique(agreements: Iterable[ResolvedLicenseAgreement]) -> list[ResolvedLicenseAgreement]:
    """Drop repeated agreements - different ids with identical terms and affirmation share one hash."""
    seen: set[str] = set()
    unique = []
    for agreement in agreements:
        if agreement.agreement_hash not in seen:
            seen.add(agreement.agreement_hash)
            unique.append(agreement)
    return unique
