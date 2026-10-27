from galaxy.managers.comparison_cells import ComparisonAccess
from galaxy.managers.comparisons import ComparisonsManager
from galaxy.managers.context import ProvidesUserContext
from galaxy.managers.workflows import WorkflowsManager
from galaxy.schema.comparisons import (
    ComparisonTable,
    StepRunsQuery,
)
from galaxy.security.idencoding import IdEncodingHelper
from galaxy.webapps.galaxy.services.base import ServiceBase


class ComparisonsService(ServiceBase):
    """Tables comparing runs of a workflow step, a workflow's outputs, or a tool."""

    def __init__(
        self,
        security: IdEncodingHelper,
        workflows_manager: WorkflowsManager,
        comparisons_manager: ComparisonsManager,
    ):
        super().__init__(security=security)
        self._workflows_manager = workflows_manager
        self._comparisons_manager = comparisons_manager

    def step_runs(
        self, trans: ProvidesUserContext, query: StepRunsQuery, instance: bool = False
    ) -> tuple[ComparisonTable, int]:
        stored_workflow = self._workflows_manager.get_stored_accessible_workflow(
            trans, query.workflow_id, by_stored_id=not instance
        )
        query = query.model_copy(update={"workflow_id": stored_workflow.id})
        access = _access(trans)
        if access is None:
            return ComparisonTable(query=query, columns=[], rows=[]), 0
        return self._comparisons_manager.step_runs(access, stored_workflow.id, query)


def _access(trans: ProvidesUserContext) -> ComparisonAccess | None:
    """The caller's access context; None for anonymous callers, who have no runs."""
    if trans.user is None:
        return None
    role_ids = frozenset(role.id for role in trans.get_current_user_roles())
    return ComparisonAccess(user_id=trans.user.id, role_ids=role_ids, is_admin=trans.user_is_admin)
