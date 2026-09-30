from sqlalchemy import (
    func,
    select,
)
from sqlalchemy.orm import aliased

from galaxy.model import ToolLicenseAcceptanceEvent
from galaxy.model.scoped_session import galaxy_scoped_session


def get_latest_license_acceptance_events(
    session: galaxy_scoped_session, user_id: int
) -> dict[str, ToolLicenseAcceptanceEvent]:
    """Newest acceptance event per agreement hash for a user.

    Ordered by primary key rather than timestamp so simultaneous events resolve deterministically.
    """
    ranked = (
        select(
            ToolLicenseAcceptanceEvent,
            func.row_number()
            .over(partition_by=ToolLicenseAcceptanceEvent.agreement_hash, order_by=ToolLicenseAcceptanceEvent.id.desc())
            .label("rank"),
        )
        .where(ToolLicenseAcceptanceEvent.user_id == user_id)
        .subquery()
    )
    latest = aliased(ToolLicenseAcceptanceEvent, ranked)
    stmt = select(latest).where(ranked.c.rank == 1)
    return {event.agreement_hash: event for event in session.scalars(stmt)}


def get_accepted_license_agreements(
    session: galaxy_scoped_session, user_id: int
) -> dict[str, ToolLicenseAcceptanceEvent]:
    """Agreements the user currently accepts, mapped to the accepting event."""
    return {
        agreement_hash: event
        for agreement_hash, event in get_latest_license_acceptance_events(session, user_id).items()
        if event.action == "accept"
    }
