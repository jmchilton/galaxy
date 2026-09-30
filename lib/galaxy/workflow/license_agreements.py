"""License agreements declared by the tools of a workflow, checked when it is invoked."""

from collections.abc import Collection
from dataclasses import (
    dataclass,
    field,
)
from typing import TYPE_CHECKING

from galaxy.managers.license_agreements import (
    LicenseAcceptanceManager,
    validate_one_time_hashes,
)
from galaxy.schema.license_agreements import (
    LicenseAgreementDeclaringStep,
    WorkflowLicenseAgreementResponse,
)
from galaxy.schema.schema import UnmetPrecondition
from galaxy.tool_util.license_agreements import ResolvedLicenseAgreement
from galaxy.tool_util.toolbox.base import MaterializationReasonName
from galaxy.tools.preconditions import ToolExecutionPreconditionUnmet

if TYPE_CHECKING:
    from galaxy.managers.context import ProvidesUserContext
    from galaxy.model import (
        Workflow,
        WorkflowStep,
    )
    from galaxy.tools import Tool


@dataclass
class DeclaringStep:
    # Order indices from the outermost workflow down to the step, through subworkflows.
    path: tuple[int, ...]
    step: "WorkflowStep"
    tool: "Tool"


@dataclass
class DeclaredLicenseAgreement:
    agreement: ResolvedLicenseAgreement
    steps: list[DeclaringStep] = field(default_factory=list)


@dataclass
class WorkflowLicenseAgreements:
    declared: dict[str, DeclaredLicenseAgreement]
    # Validated agreement hashes accepted for this invocation only.
    one_time: set[str]

    def one_time_by_step(self) -> dict[int, list[str]]:
        """One-time accepted agreement hashes by the id of each workflow step declaring them."""
        by_step: dict[int, list[str]] = {}
        for agreement_hash in self.one_time:
            for declaring in self.declared[agreement_hash].steps:
                by_step.setdefault(declaring.step.id, []).append(agreement_hash)
        return by_step


def workflow_license_agreements(
    trans: "ProvidesUserContext", workflow: "Workflow", reason: MaterializationReasonName = "execution"
) -> dict[str, DeclaredLicenseAgreement]:
    """Agreements declared by the workflow's tool steps, including those of subworkflows, by agreement hash."""
    toolbox = trans.app.toolbox
    declared: dict[str, DeclaredLicenseAgreement] = {}
    tools: dict[int, Tool] = {}
    for path, step in workflow.walk_tool_steps():
        tool_like = toolbox.get_tool(
            step.effective_tool_id, tool_version=step.tool_version, tool_uuid=step.tool_uuid, user=trans.user
        )
        if tool_like is None:
            # Missing tools are reported before invocation by the caller.
            continue
        if (tool := tools.get(id(tool_like))) is None:
            tool = tools[id(tool_like)] = toolbox.materialize_tool(tool_like, reason=reason)
        for agreement in tool.license_agreements:
            entry = declared.setdefault(agreement.agreement_hash, DeclaredLicenseAgreement(agreement))
            entry.steps.append(DeclaringStep(path, step, tool))
    return declared


def check_workflow_license_agreements(
    trans: "ProvidesUserContext", workflow: "Workflow", one_time_license_acceptances: Collection[str]
) -> WorkflowLicenseAgreements:
    """Validate an invocation request's one-time acceptances and require every declared agreement be accepted.

    The terms of validated one-time acceptances are stored, so invocations can be pinned to them.
    """
    declared = workflow_license_agreements(trans, workflow)
    agreements = [entry.agreement for entry in declared.values()]
    one_time = validate_one_time_hashes(agreements, one_time_license_acceptances)
    authorization = trans.app[LicenseAcceptanceManager].authorize(trans.user, agreements, one_time)
    if authorization.unmet:
        unmet = _describe(trans, declared, authorization.unmet)
        raise ToolExecutionPreconditionUnmet(
            [
                UnmetPrecondition(
                    kind="license_agreement",
                    message="Workflow requires accepting license agreements "
                    f"[{', '.join(agreement.agreement.id for agreement in authorization.unmet)}].",
                    details={"agreements": [agreement.model_dump() for agreement in unmet]},
                )
            ]
        )
    return WorkflowLicenseAgreements(declared=declared, one_time=one_time)


def describe_workflow_license_agreements(
    trans: "ProvidesUserContext", workflow: "Workflow"
) -> list[WorkflowLicenseAgreementResponse]:
    """Agreements the workflow's tools declare as shown to the user, each with the steps declaring it."""
    declared = workflow_license_agreements(trans, workflow, reason="validation")
    return _describe(trans, declared, [entry.agreement for entry in declared.values()])


def _describe(
    trans: "ProvidesUserContext",
    declared: dict[str, DeclaredLicenseAgreement],
    agreements: list[ResolvedLicenseAgreement],
) -> list[WorkflowLicenseAgreementResponse]:
    return [
        WorkflowLicenseAgreementResponse(
            **agreement.model_dump(),
            steps=[
                LicenseAgreementDeclaringStep(
                    path=list(declaring.path), tool_id=declaring.tool.id, tool_version=declaring.tool.version
                )
                for declaring in declared[agreement.agreement_hash].steps
            ],
        )
        for agreement in trans.app[LicenseAcceptanceManager].describe(trans.user, agreements)
    ]
