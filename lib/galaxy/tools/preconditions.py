"""Conditions that must hold before a tool may create a job.

Checked by :class:`galaxy.tools.actions.DefaultToolAction` (and subclasses that
defer to its ``execute``) before each job is created. Tool actions that
override ``execute`` without calling it - model operations, upload, set
metadata, history import/export - do not check these.
"""

import abc
from typing import TYPE_CHECKING

from galaxy.exceptions import ItemAccessibilityException
from galaxy.exceptions.error_codes import error_codes_by_name
from galaxy.schema.tool_preconditions import UnmetPrecondition

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


class ToolExecutionPrecondition(abc.ABC):
    """A condition that must hold before a tool may create a job."""

    # When unmet, skip remaining preconditions - e.g. don't describe a tool's
    # requirements to a user who may not access the tool at all.
    short_circuit: bool = False

    @abc.abstractmethod
    def unmet(self, trans: "ProvidesUserContext", tool: "Tool") -> UnmetPrecondition | None:
        """Return ``None`` if the condition holds, otherwise describe what is missing."""


class ToolAccessPrecondition(ToolExecutionPrecondition):
    """The user may access the tool at all (``require_login``, admin-only and unprivileged tools)."""

    short_circuit = True

    def unmet(self, trans: "ProvidesUserContext", tool: "Tool") -> UnmetPrecondition | None:
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


def check_preconditions(
    trans: "ProvidesUserContext", tool: "Tool", preconditions: list[ToolExecutionPrecondition]
) -> None:
    unmet: list[UnmetPrecondition] = []
    for precondition in preconditions:
        if (result := precondition.unmet(trans, tool)) is not None:
            unmet.append(result)
            if precondition.short_circuit:
                break
    if unmet:
        raise ToolExecutionPreconditionUnmet(unmet)
