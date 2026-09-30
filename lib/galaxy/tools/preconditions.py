"""Conditions that must hold before a tool may create a job.

Checked by :class:`galaxy.tools.actions.DefaultToolAction` (and subclasses that
defer to its ``execute``) before each job is created. Tool actions that
override ``execute`` without calling it - model operations, upload, set
metadata, history import/export - do not check these, so tools declaring
license agreements may not use them (see ``ToolAction.checks_preconditions``).
"""

import abc
from collections.abc import Collection
from dataclasses import (
    dataclass,
    field,
)
from typing import (
    Any,
    TYPE_CHECKING,
)

from galaxy.exceptions import ItemAccessibilityException
from galaxy.exceptions.error_codes import error_codes_by_name
from galaxy.managers.license_agreements import (
    LicenseAcceptanceManager,
    LicenseAgreementAuthorization,
)
from galaxy.schema.schema import UnmetPrecondition
from galaxy.tool_util.license_agreements import ResolvedLicenseAgreement

if TYPE_CHECKING:
    from galaxy.managers.context import ProvidesUserContext
    from galaxy.tools import Tool


class ToolExecutionPreconditionUnmet(ItemAccessibilityException):
    err_code = error_codes_by_name["TOOL_EXECUTION_PRECONDITION_UNMET"]

    def __init__(self, unmet: list[UnmetPrecondition]):
        self.unmet = unmet
        super().__init__(
            "; ".join(u.message for u in unmet),
            unmet=[u.model_dump() for u in unmet],
        )


@dataclass
class ToolExecutionContext:
    """What a submission carries for preconditions - shared by every job it creates."""

    # Agreement hashes the user accepted for this submission only.
    one_time_license_acceptances: Collection[str] = frozenset()
    # Resolved once per set of agreements so every job records the authorization its submission was checked against.
    license_authorizations: dict[tuple[str, ...], LicenseAgreementAuthorization] = field(default_factory=dict)


class ToolExecutionPrecondition(abc.ABC):
    """A condition that must hold before a tool may create a job."""

    # When unmet, skip remaining preconditions - e.g. don't describe a tool's
    # requirements to a user who may not access the tool at all.
    short_circuit: bool = False

    @abc.abstractmethod
    def unmet(
        self, trans: "ProvidesUserContext", tool: "Tool", context: ToolExecutionContext
    ) -> UnmetPrecondition | None:
        """Return ``None`` if the condition holds, otherwise describe what is missing."""


class ToolAccessPrecondition(ToolExecutionPrecondition):
    """The user may access the tool at all (``require_login``, admin-only and unprivileged tools)."""

    short_circuit = True

    def unmet(
        self, trans: "ProvidesUserContext", tool: "Tool", context: ToolExecutionContext
    ) -> UnmetPrecondition | None:
        if tool.allow_user_access(trans.user):
            return None
        login_required = trans.user is None and tool.require_login
        return UnmetPrecondition(
            kind="access",
            message=f"Tool '{tool.id}' requires login." if login_required else f"Tool '{tool.id}' is not accessible.",
            details={"tool_id": tool.id},
            remedy_route="/login/start" if login_required else None,
        )


TOOL_ACCESS_PRECONDITION = ToolAccessPrecondition()


class LicenseAcceptancePrecondition(ToolExecutionPrecondition):
    """Every license agreement the tool declares is accepted, persistently or for this submission."""

    def unmet(
        self, trans: "ProvidesUserContext", tool: "Tool", context: ToolExecutionContext
    ) -> UnmetPrecondition | None:
        unmet = self.authorization(trans, tool, context).unmet
        if not unmet:
            return None
        return UnmetPrecondition(
            kind="license_agreement",
            message=f"Tool '{tool.id}' requires accepting license agreements "
            f"[{', '.join(agreement.agreement.id for agreement in unmet)}].",
            details={
                "tool_id": tool.id,
                "tool_version": tool.version,
                "agreements": [license_agreement_details(agreement) for agreement in unmet],
            },
        )

    def authorization(
        self, trans: "ProvidesUserContext", tool: "Tool", context: ToolExecutionContext
    ) -> LicenseAgreementAuthorization:
        """How the tool's agreements are authorized for this submission, resolved on first use."""
        key = tuple(agreement.agreement_hash for agreement in tool.license_agreements)
        if key not in context.license_authorizations:
            context.license_authorizations[key] = trans.app[LicenseAcceptanceManager].authorize(
                trans.user, tool.license_agreements, context.one_time_license_acceptances
            )
        return context.license_authorizations[key]


LICENSE_ACCEPTANCE_PRECONDITION = LicenseAcceptancePrecondition()


def license_agreement_details(agreement: ResolvedLicenseAgreement) -> dict[str, Any]:
    """What a client needs to prompt for an unmet agreement."""
    declared = agreement.agreement
    return {
        "id": declared.id,
        "version": declared.version,
        "label": declared.label,
        "url": declared.url,
        "affirmation": declared.affirmation,
        "binds": declared.binds,
        "agreement_hash": agreement.agreement_hash,
    }


def check_preconditions(
    trans: "ProvidesUserContext",
    tool: "Tool",
    preconditions: list[ToolExecutionPrecondition],
    context: ToolExecutionContext | None = None,
) -> None:
    context = context or ToolExecutionContext()
    unmet: list[UnmetPrecondition] = []
    for precondition in preconditions:
        if (result := precondition.unmet(trans, tool, context)) is not None:
            unmet.append(result)
            if precondition.short_circuit:
                break
    if unmet:
        raise ToolExecutionPreconditionUnmet(unmet)
