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
        if trans.user is None:
            return ComparisonTable(query=query, columns=[], rows=[]), 0
        return self._comparisons_manager.step_runs(trans.user.id, stored_workflow.id, query)
