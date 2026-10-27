from collections.abc import Callable
from typing import TypeVar

from galaxy.managers.comparison_cells import ComparisonAccess
from galaxy.managers.comparisons import ComparisonsManager
from galaxy.managers.context import ProvidesUserContext
from galaxy.managers.workflows import WorkflowsManager
from galaxy.schema.comparisons import (
    ComparisonTable,
    OutputRunsQuery,
    StepRunsQuery,
    ToolRunsQuery,
)
from galaxy.security.idencoding import IdEncodingHelper
from galaxy.webapps.galaxy.services.base import ServiceBase

WorkflowQueryT = TypeVar("WorkflowQueryT", StepRunsQuery, OutputRunsQuery)
QueryT = TypeVar("QueryT", StepRunsQuery, OutputRunsQuery, ToolRunsQuery)


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
        query = self._with_stored_workflow_id(trans, query, instance)
        return _compare(trans, query, self._comparisons_manager.step_runs)

    def output_runs(
        self, trans: ProvidesUserContext, query: OutputRunsQuery, instance: bool = False
    ) -> tuple[ComparisonTable, int]:
        query = self._with_stored_workflow_id(trans, query, instance)
        return _compare(trans, query, self._comparisons_manager.output_runs)

    def tool_runs(self, trans: ProvidesUserContext, query: ToolRunsQuery) -> tuple[ComparisonTable, int]:
        return _compare(trans, query, self._comparisons_manager.tool_runs)

    def _with_stored_workflow_id(
        self, trans: ProvidesUserContext, query: WorkflowQueryT, instance: bool
    ) -> WorkflowQueryT:
        """Check the workflow is accessible and normalize ``workflow_id`` to the StoredWorkflow id."""
        stored_workflow = self._workflows_manager.get_stored_accessible_workflow(
            trans, query.workflow_id, by_stored_id=not instance
        )
        return query.model_copy(update={"workflow_id": stored_workflow.id})


def _compare(
    trans: ProvidesUserContext,
    query: QueryT,
    resolve: Callable[[ComparisonAccess, QueryT], tuple[ComparisonTable, int]],
) -> tuple[ComparisonTable, int]:
    """Resolve ``query`` for the caller; anonymous callers have no runs, so an empty table."""
    if trans.user is None:
        return ComparisonTable(query=query, columns=[], rows=[]), 0
    role_ids = frozenset(role.id for role in trans.get_current_user_roles())
    access = ComparisonAccess(user_id=trans.user.id, role_ids=role_ids, is_admin=trans.user_is_admin)
    return resolve(access, query)
