"""API for comparing runs of a workflow step, a workflow's outputs, or a tool."""

from typing import Annotated

from fastapi import (
    Depends,
    Path,
    Query,
    Response,
)
from pydantic import ValidationError

from galaxy.exceptions.utils import validation_error_to_message_exception
from galaxy.managers.context import ProvidesUserContext
from galaxy.schema.comparisons import (
    COMPARISON_LIMIT_BOUND,
    COMPARISON_LIMIT_DEFAULT,
    COMPARISON_LIMIT_MIN,
    COMPARISON_OFFSET_MIN,
    COMPARISON_QUERY_DESCRIPTIONS,
    ComparisonQueryBase,
    ComparisonSortBy,
    ComparisonTable,
    OutputRunsQuery,
    StepRunsQuery,
    ToolRunsQuery,
)
from galaxy.schema.fields import DecodedDatabaseIdField
from galaxy.webapps.galaxy.api import (
    depends,
    DependsOnTrans,
    Router,
)
from galaxy.webapps.galaxy.api.common import query_parameter_as_list
from galaxy.webapps.galaxy.services.comparisons import ComparisonsService

router = Router(tags=["comparisons"])

StoredWorkflowIDPathParam = Annotated[
    DecodedDatabaseIdField,
    Path(
        ...,
        title="Stored Workflow ID",
        description="The encoded id of the Stored Workflow, or of a Workflow version with `instance=true`.",
    ),
]

InstanceQueryParam = Annotated[
    bool,
    Query(title="True when `workflow_id` is a Workflow version id, False when it is a StoredWorkflow id."),
]

StepLabelQueryParam = Annotated[
    str,
    Query(min_length=1, title="Step label", description="Label of the step to compare across invocations."),
]

VersionsQueryParam = Annotated[
    list[int] | None,
    Query(
        title="Versions",
        description="Only include runs of these 0-based workflow versions. Repeat the parameter for several.",
    ),
]

OutputLabelsQueryParam = Annotated[
    list[str] | None,
    Query(
        title="Output labels",
        description=(
            "Only include these labelled workflow outputs; labelled inputs and parameters are always included. "
            "Repeat the parameter for several."
        ),
    ),
]

LIST_DESCRIPTION_SUFFIX = " A comma-separated list or repeated parameter."

ToolIdQueryParam = Annotated[
    str,
    Query(min_length=1, title="Tool ID", description="Tool id; a Tool Shed version suffix is ignored."),
]

ToolVersionsQueryParam = Query(
    default=None,
    alias="tool_versions",
    title="Tool versions",
    description="Only include runs of these tool versions." + LIST_DESCRIPTION_SUFFIX,
)

ToolRunsHistoryIdQueryParam = Annotated[
    DecodedDatabaseIdField | None,
    Query(title="History ID", description="Only include runs in this history."),
]

IncludeWorkflowJobsQueryParam = Annotated[
    bool,
    Query(title="Include workflow jobs", description="Include jobs run as part of a workflow invocation."),
]

StatesQueryParam = Query(
    default=None,
    alias="states",
    title="States",
    description=COMPARISON_QUERY_DESCRIPTIONS["states"] + LIST_DESCRIPTION_SUFFIX,
)

MetadataElementsQueryParam = Query(
    default=None,
    alias="metadata_elements",
    title="Metadata elements",
    description=COMPARISON_QUERY_DESCRIPTIONS["metadata_elements"] + LIST_DESCRIPTION_SUFFIX,
)


def comparison_query_params(
    limit: int = Query(
        COMPARISON_LIMIT_DEFAULT,
        ge=COMPARISON_LIMIT_MIN,
        lt=COMPARISON_LIMIT_BOUND,
        description=COMPARISON_QUERY_DESCRIPTIONS["limit"],
    ),
    offset: int = Query(0, ge=COMPARISON_OFFSET_MIN, description=COMPARISON_QUERY_DESCRIPTIONS["offset"]),
    sort_by: ComparisonSortBy = Query("create_time", description=COMPARISON_QUERY_DESCRIPTIONS["sort_by"]),
    sort_desc: bool = Query(True, description=COMPARISON_QUERY_DESCRIPTIONS["sort_desc"]),
    states: list[str] | None = Depends(query_parameter_as_list(StatesQueryParam)),
    metadata_elements: list[str] | None = Depends(query_parameter_as_list(MetadataElementsQueryParam)),
    inline_expression_values: bool = Query(True, description=COMPARISON_QUERY_DESCRIPTIONS["inline_expression_values"]),
) -> ComparisonQueryBase:
    """Query parameters shared by every comparison endpoint."""
    try:
        return ComparisonQueryBase(
            limit=limit,
            offset=offset,
            sort_by=sort_by,
            sort_desc=sort_desc,
            states=states,
            metadata_elements=metadata_elements or [],
            inline_expression_values=inline_expression_values,
        )
    except ValidationError as e:
        raise validation_error_to_message_exception(e)


@router.cbv
class FastAPIComparisons:
    service: ComparisonsService = depends(ComparisonsService)

    @router.get(
        "/api/workflows/{workflow_id}/step_runs",
        summary="Compare runs of a labelled workflow step across the workflow's invocations.",
    )
    def step_runs(
        self,
        response: Response,
        workflow_id: StoredWorkflowIDPathParam,
        step_label: StepLabelQueryParam,
        versions: VersionsQueryParam = None,
        instance: InstanceQueryParam = False,
        comparison_params: ComparisonQueryBase = Depends(comparison_query_params),
        trans: ProvidesUserContext = DependsOnTrans,
    ) -> ComparisonTable:
        query = StepRunsQuery.model_construct(
            **comparison_params.model_dump(), workflow_id=workflow_id, step_label=step_label, versions=versions
        )
        table, total_matches = self.service.step_runs(trans, query, instance)
        response.headers["total_matches"] = str(total_matches)
        return table

    @router.get(
        "/api/workflows/{workflow_id}/output_runs",
        summary="Compare a workflow's labelled inputs and outputs across its invocations.",
    )
    def output_runs(
        self,
        response: Response,
        workflow_id: StoredWorkflowIDPathParam,
        output_labels: OutputLabelsQueryParam = None,
        instance: InstanceQueryParam = False,
        comparison_params: ComparisonQueryBase = Depends(comparison_query_params),
        trans: ProvidesUserContext = DependsOnTrans,
    ) -> ComparisonTable:
        query = OutputRunsQuery.model_construct(
            **comparison_params.model_dump(), workflow_id=workflow_id, output_labels=output_labels
        )
        table, total_matches = self.service.output_runs(trans, query, instance)
        response.headers["total_matches"] = str(total_matches)
        return table

    @router.get(
        "/api/tool_runs",
        summary="Compare runs of a tool across its versions.",
    )
    def tool_runs(
        self,
        response: Response,
        tool_id: ToolIdQueryParam,
        tool_versions: list[str] | None = Depends(query_parameter_as_list(ToolVersionsQueryParam)),
        history_id: ToolRunsHistoryIdQueryParam = None,
        include_workflow_jobs: IncludeWorkflowJobsQueryParam = True,
        comparison_params: ComparisonQueryBase = Depends(comparison_query_params),
        trans: ProvidesUserContext = DependsOnTrans,
    ) -> ComparisonTable:
        query = ToolRunsQuery.model_construct(
            **comparison_params.model_dump(),
            tool_id=tool_id,
            tool_versions=tool_versions,
            history_id=history_id,
            include_workflow_jobs=include_workflow_jobs,
        )
        table, total_matches = self.service.tool_runs(trans, query)
        response.headers["total_matches"] = str(total_matches)
        return table
