from dataclasses import (
    dataclass,
    field,
)
from typing import (
    Any,
    cast,
)

import pytest

from galaxy import model
from galaxy.managers.context import ProvidesUserContext
from galaxy.tool_util.license_agreements import (
    resolve_license_agreement,
    ResolvedLicenseAgreement,
)
from galaxy.tool_util_models.tool_source import LicenseAgreement
from galaxy.tools.preconditions import ToolExecutionPreconditionUnmet
from galaxy.workflow.license_agreements import check_workflow_license_agreements


def _agreement() -> ResolvedLicenseAgreement:
    return resolve_license_agreement(
        LicenseAgreement(id="terms", version="1", label="Terms", affirmation="I agree", text="Secret terms"), None
    )


@dataclass
class StubTool:
    id: str = "admin_only_tool"
    version: str = "1.0"
    require_login: bool = True
    license_agreements: list[ResolvedLicenseAgreement] = field(default_factory=lambda: [_agreement()])

    def allow_user_access(self, user, attempting_access: bool = True) -> bool:
        return False


@dataclass
class StubToolbox:
    tool: StubTool

    def get_tool(self, tool_id, **kwds) -> StubTool:
        return self.tool

    def materialize_tool(self, tool, reason) -> StubTool:
        return tool


@dataclass
class StubApp:
    toolbox: StubToolbox

    def __getitem__(self, key):
        raise AssertionError(f"{key} must not be consulted for an inaccessible tool")


@dataclass
class StubTrans:
    app: StubApp
    user: Any = field(default_factory=object)


def _workflow(*tool_ids: str) -> model.Workflow:
    workflow = model.Workflow()
    for order_index, tool_id in enumerate(tool_ids):
        step = model.WorkflowStep()
        step.order_index = order_index
        step.type = "tool"
        step.tool_id = tool_id
        workflow.steps.append(step)
    return workflow


def test_invocation_check_refuses_inaccessible_licensed_tool_once_without_authorizing():
    trans = cast(ProvidesUserContext, StubTrans(app=StubApp(StubToolbox(StubTool()))))
    with pytest.raises(ToolExecutionPreconditionUnmet) as exc_info:
        check_workflow_license_agreements(trans, _workflow("admin_only_tool", "admin_only_tool"), [])
    (unmet,) = exc_info.value.unmet
    assert unmet.model_dump() == {
        "kind": "access",
        "message": "Tool 'admin_only_tool' is not accessible.",
        "details": {"tool_id": "admin_only_tool"},
        "remedy_route": None,
    }
