"""Models for comparing runs of a workflow step, a workflow's outputs, or a tool."""

import re
from datetime import datetime
from typing import (
    Annotated,
    Any,
    Literal,
)

from pydantic import (
    Field,
    field_validator,
)

from galaxy.schema.fields import (
    DecodedDatabaseIdField,
    EncodedDatabaseIdField,
)
from galaxy.schema.schema import (
    CollectionType,
    CollectionTypeField,
    DatasetStateField,
    ElementCountField,
    HistoryID,
    ImplicitCollectionJobsStateSummary,
    Model,
    PopulatedStateField,
)
from galaxy.schema.states import (
    DatasetCollectionPopulatedState,
    InvocationState,
    JobState,
)

ComparisonSortBy = Literal["create_time", "update_time"]
MissingReason = Literal["not_in_version", "skipped", "not_run_yet", "no_output", "inaccessible"]
ComparisonColumnRole = Literal["input", "output", "parameter"]
ReusedState = Literal["no", "partial", "yes"]
# keys of galaxy.workflow.modules.module_types
WorkflowStepModuleType = Literal[
    "data_input", "data_collection_input", "parameter_input", "pause", "pick_value", "tool", "subworkflow"
]

METADATA_ELEMENT_PATTERN = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")

# shared with the API query parameters
COMPARISON_LIMIT_DEFAULT = 25
COMPARISON_LIMIT_MIN = 1
COMPARISON_LIMIT_BOUND = 1000
COMPARISON_OFFSET_MIN = 0
COMPARISON_QUERY_DESCRIPTIONS = {
    "limit": "Maximum number of rows to return.",
    "offset": "Number of rows to skip.",
    "sort_by": "Sort rows by this run attribute.",
    "sort_desc": "Sort rows in descending order.",
    "states": "Only include runs in one of these states.",
    "metadata_elements": "Metadata element names to include in dataset cells, e.g. `data_lines`.",
    "inline_expression_values": "Render small `expression.json` outputs as their value instead of a dataset.",
}


class ComparisonQueryBase(Model):
    limit: int = Field(
        COMPARISON_LIMIT_DEFAULT,
        ge=COMPARISON_LIMIT_MIN,
        lt=COMPARISON_LIMIT_BOUND,
        description=COMPARISON_QUERY_DESCRIPTIONS["limit"],
    )
    offset: int = Field(0, ge=COMPARISON_OFFSET_MIN, description=COMPARISON_QUERY_DESCRIPTIONS["offset"])
    sort_by: ComparisonSortBy = Field("create_time", description=COMPARISON_QUERY_DESCRIPTIONS["sort_by"])
    sort_desc: bool = Field(True, description=COMPARISON_QUERY_DESCRIPTIONS["sort_desc"])
    states: list[str] | None = Field(None, description=COMPARISON_QUERY_DESCRIPTIONS["states"])
    metadata_elements: list[str] = Field([], description=COMPARISON_QUERY_DESCRIPTIONS["metadata_elements"])
    inline_expression_values: bool = Field(True, description=COMPARISON_QUERY_DESCRIPTIONS["inline_expression_values"])

    @field_validator("metadata_elements")
    @classmethod
    def validate_metadata_elements(cls, value: list[str]) -> list[str]:
        for name in value:
            if not METADATA_ELEMENT_PATTERN.match(name):
                raise ValueError(f"Invalid metadata element name [{name}]")
        return value


class WorkflowComparisonQueryBase(ComparisonQueryBase):
    workflow_id: DecodedDatabaseIdField = Field(..., description="The StoredWorkflow id.")
    versions: list[int] | None = Field(None, description="Only include runs of these 0-based workflow versions.")


class StepRunsQuery(WorkflowComparisonQueryBase):
    kind: Literal["step_runs"] = "step_runs"
    step_label: str = Field(..., min_length=1, description="Label of the step to compare across invocations.")


class OutputRunsQuery(WorkflowComparisonQueryBase):
    kind: Literal["output_runs"] = "output_runs"
    output_labels: list[str] | None = Field(
        None, description="Only include these labelled outputs; labelled inputs and parameters are always included."
    )


class ToolRunsQuery(ComparisonQueryBase):
    kind: Literal["tool_runs"] = "tool_runs"
    tool_id: str = Field(..., description="Tool id; a Tool Shed version suffix is ignored.")
    tool_versions: list[str] | None = Field(None, description="Only include runs of these tool versions.")
    history_id: DecodedDatabaseIdField | None = Field(None, description="Only include runs in this history.")
    include_workflow_jobs: bool = Field(True, description="Include jobs run as part of a workflow invocation.")


AnyComparisonQuery = Annotated[StepRunsQuery | OutputRunsQuery | ToolRunsQuery, Field(discriminator="kind")]


class InvocationRunRef(Model):
    model: Literal["WorkflowInvocation"] = "WorkflowInvocation"
    id: EncodedDatabaseIdField
    state: InvocationState


class JobRunRef(Model):
    model: Literal["Job"] = "Job"
    id: EncodedDatabaseIdField
    state: JobState


class ImplicitCollectionJobsRunRef(ImplicitCollectionJobsStateSummary):
    representative_job_id: EncodedDatabaseIdField | None = Field(None, description="First job of the mapped batch.")
    job_count: int


AnyRunRef = Annotated[InvocationRunRef | JobRunRef | ImplicitCollectionJobsRunRef, Field(discriminator="model")]
AnyStepJobRef = Annotated[JobRunRef | ImplicitCollectionJobsRunRef, Field(discriminator="model")]


class HistoryRef(Model):
    id: EncodedDatabaseIdField
    name: str | None
    deleted: bool
    purged: bool


class WorkflowRunVia(Model):
    invocation_id: EncodedDatabaseIdField
    step_label: str | None = None
    workflow_name: str | None = None


class DatasetCell(Model):
    type: Literal["dataset"] = "dataset"
    id: EncodedDatabaseIdField
    hid: int | None = None
    name: str | None = None
    extension: str | None = None
    state: DatasetStateField
    deleted: bool
    purged: bool
    history_id: HistoryID
    metadata: dict[str, Any] = Field({}, description="Requested metadata elements that are set on the dataset.")


class CollectionCell(Model):
    type: Literal["collection"] = "collection"
    id: EncodedDatabaseIdField
    hid: int | None = None
    name: str | None = None
    collection_type: CollectionType = CollectionTypeField
    element_count: ElementCountField
    populated_state: DatasetCollectionPopulatedState = PopulatedStateField
    deleted: bool
    history_id: HistoryID


class ValueCell(Model):
    type: Literal["value"] = "value"
    value: Any
    source: Literal["parameter", "output_value", "expression_json"]
    dataset_id: EncodedDatabaseIdField | None = Field(
        None, description="The dataset an expression value was read from."
    )


class MissingCell(Model):
    type: Literal["missing"] = "missing"
    reason: MissingReason


AnyComparisonCell = Annotated[DatasetCell | CollectionCell | ValueCell | MissingCell, Field(discriminator="type")]


class ComparisonColumn(Model):
    key: str = Field(..., description="Role-prefixed name, e.g. `output:out_file1`; keys `ComparisonRow.cells`.")
    label: str
    role: ComparisonColumnRole
    present_in_versions: list[int] | None = Field(
        None, description="Versions on the page that have this column; null when every version has it."
    )
    duplicate: bool = Field(False, description="Some version declares more than one item with this label.")
    metadata_keys: list[str] = Field(
        [], description="Scalar metadata element names declared by the datatypes of this column's datasets, set or not."
    )


class ComparisonRow(Model):
    run: AnyRunRef
    step_job: AnyStepJobRef | None = Field(None, description="The job or mapped batch that ran the compared step.")
    subworkflow_invocation_id: EncodedDatabaseIdField | None = None
    step_type: WorkflowStepModuleType | None = Field(None, description="Module type of the compared step in this run.")
    step_action: bool | None = Field(None, description="A pause step's review decision; null until reviewed.")
    via: WorkflowRunVia | None = Field(None, description="The invocation a tool run belongs to.")
    create_time: datetime
    update_time: datetime
    state: str
    version: int | None = Field(None, description="0-based workflow version of the run.")
    tool_id: str | None = None
    tool_version: str | None = None
    reused: ReusedState | None = Field(None, description="Whether job outputs came from the job cache.")
    history: HistoryRef
    cells: dict[str, AnyComparisonCell] = Field(..., description="One cell per column key.")


class ComparisonTable(Model):
    query: AnyComparisonQuery
    columns: list[ComparisonColumn]
    rows: list[ComparisonRow]
    tool_versions_available: list[str] | None = None
    versions_available: list[int] | None = Field(
        None,
        description=(
            "0-based workflow versions to filter by, whatever `versions` selects: those with the compared step"
            " for step runs, every version for output runs."
        ),
    )
    output_labels_available: list[str] | None = Field(
        None, description="Output labels of the workflow versions the caller has run, whatever `output_labels` selects."
    )
