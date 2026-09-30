from galaxy.exceptions import (
    ObjectNotFound,
    RequestParameterInvalidException,
)
from galaxy.managers.context import ProvidesUserContext
from galaxy.managers.license_agreements import LicenseAcceptanceManager
from galaxy.model import ToolLicenseAcceptanceEvent
from galaxy.schema.license_agreements import (
    CreateLicenseAcceptancePayload,
    LicenseAcceptanceEventResponse,
    LicenseAcceptanceResponse,
    LicenseAgreementTermsResponse,
    ToolLicenseAgreementsResponse,
    UserLicenseAcceptancesResponse,
)
from galaxy.schema.schema import FlexibleUserIdType
from galaxy.webapps.galaxy.services.base import ensure_user_access
from galaxy.webapps.galaxy.services.tools import get_accessible_tool


class LicenseAgreementsService:
    """Tool license agreements and the current user's acceptance of them."""

    def __init__(self, license_acceptance_manager: LicenseAcceptanceManager) -> None:
        self.license_acceptance_manager = license_acceptance_manager

    def tool_license_agreements(
        self, trans: ProvidesUserContext, tool_id: str, tool_version: str | None
    ) -> ToolLicenseAgreementsResponse:
        tool = get_accessible_tool(trans, tool_id, tool_version, reason="detail")
        return ToolLicenseAgreementsResponse(
            root=self.license_acceptance_manager.describe(trans.user, tool.license_agreements)
        )

    def list_acceptances(
        self, trans: ProvidesUserContext, user_id: FlexibleUserIdType, include_history: bool
    ) -> UserLicenseAcceptancesResponse:
        user = ensure_user_access(trans, user_id, "license acceptances")
        accepted = self.license_acceptance_manager.current_state(user).values()
        history = self.license_acceptance_manager.history(user) if include_history else None
        return UserLicenseAcceptancesResponse(
            accepted=[_acceptance_response(event) for event in sorted(accepted, key=lambda event: event.id)],
            history=[_event_response(event) for event in history] if history is not None else None,
        )

    def accept(
        self, trans: ProvidesUserContext, user_id: FlexibleUserIdType, payload: CreateLicenseAcceptancePayload
    ) -> LicenseAcceptanceResponse:
        """Persistently accept an agreement the installed tool declares - terms are never taken from the client."""
        user = ensure_user_access(trans, user_id, "license acceptances")
        try:
            tool = get_accessible_tool(trans, payload.tool_id, payload.tool_version, reason="detail")
        except ObjectNotFound as e:
            raise RequestParameterInvalidException(str(e)) from e
        agreement = next((a for a in tool.license_agreements if a.agreement.id == payload.license_id), None)
        if agreement is None:
            raise RequestParameterInvalidException(
                f"Tool '{tool.id}' does not declare license agreement [{payload.license_id}]."
            )
        if agreement.agreement_hash != payload.agreement_hash:
            raise RequestParameterInvalidException(
                f"License agreement [{payload.license_id}] of tool '{tool.id}' has changed since it was displayed - "
                "review the current terms and accept again."
            )
        event = self.license_acceptance_manager.accept(
            user, agreement, prompting_tool_id=tool.id, prompting_tool_version=tool.version
        )
        trans.sa_session.commit()
        return _acceptance_response(event)

    def revoke(self, trans: ProvidesUserContext, user_id: FlexibleUserIdType, agreement_hash: str) -> None:
        user = ensure_user_access(trans, user_id, "license acceptances")
        self.license_acceptance_manager.revoke(user, agreement_hash)
        trans.sa_session.commit()


def _event_response(event: ToolLicenseAcceptanceEvent) -> LicenseAcceptanceEventResponse:
    return LicenseAcceptanceEventResponse.model_validate(event, from_attributes=True)


def _acceptance_response(event: ToolLicenseAcceptanceEvent) -> LicenseAcceptanceResponse:
    return LicenseAcceptanceResponse(
        agreement=LicenseAgreementTermsResponse.model_validate(event.agreement, from_attributes=True),
        event=_event_response(event),
    )
