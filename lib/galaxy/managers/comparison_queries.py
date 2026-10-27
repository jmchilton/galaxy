"""SQL statements and filter predicates for comparison tables."""

from collections.abc import (
    Collection,
    Mapping,
)
from datetime import datetime
from typing import (
    Any,
    NamedTuple,
)

from sqlalchemy import (
    and_,
    case,
    func,
    or_,
    select,
    Select,
)
from sqlalchemy.orm import (
    aliased,
    InstrumentedAttribute,
)
from sqlalchemy.sql.elements import ColumnElement

from galaxy.managers.comparison_states import (
    EMPTY_BATCH_STATES,
    SUMMARY_OK_RANK,
    summary_ranks,
    SUMMARY_SKIPPED_RANK,
    SUMMARY_STATE_GROUPS,
)
from galaxy.model import (
    History,
    ImplicitCollectionJobs,
    ImplicitCollectionJobsJobAssociation,
    Job,
    WorkflowInvocation,
    WorkflowInvocationStep,
    WorkflowOutput,
    WorkflowStep,
)
from galaxy.schema.comparisons import ToolRunsQuery
from galaxy.schema.states import (
    InvocationState,
    JobState,
)
from galaxy.util.tool_version import versionless_tool_id


class InvocationPageRow(NamedTuple):
    """A row of ``invocations_stmt``."""

    id: int
    workflow_id: int
    state: str | None
    create_time: datetime
    update_time: datetime
    history_id: int
    history_name: str | None
    history_deleted: bool
    history_purged: bool


class ToolRunPageRow(NamedTuple):
    """A row of ``tool_submissions_stmt``."""

    job_id: int
    implicit_collection_jobs_id: int | None
    create_time: datetime
    update_time: datetime
    history_id: int
    history_name: str | None
    history_deleted: bool
    history_purged: bool


def selected_versions(version_map: Mapping[int, int], versions: list[int] | None) -> list[int]:
    """Workflow ids of ``version_map`` whose 0-based version is in ``versions``; all of them for None."""
    return [workflow_id for workflow_id, version in version_map.items() if versions is None or version in versions]


def step_state_predicate(step_ids: list[int], states: list[str]) -> ColumnElement[bool]:
    """Invocations whose compared step shows one of ``states``; a step not scheduled yet counts as ``new``."""
    wis = WorkflowInvocationStep
    icj = ImplicitCollectionJobs
    step_of_invocation = and_(wis.workflow_invocation_id == WorkflowInvocation.id, wis.workflow_step_id.in_(step_ids))
    step_states: ColumnElement[bool] = wis.state.in_(states)
    if JobState.NEW in states:
        step_states = or_(step_states, wis.state.is_(None))
    clauses: list[ColumnElement[bool]] = [
        select(wis.id).join(Job, Job.id == wis.job_id).where(step_of_invocation, Job.state.in_(states)).exists(),
        select(wis.id)
        .join(icj, icj.id == wis.implicit_collection_jobs_id)
        .where(
            step_of_invocation,
            _batch_state_predicate(wis.implicit_collection_jobs_id, icj.populated_state, states),
        )
        .exists(),
        select(wis.id)
        .where(step_of_invocation, wis.job_id.is_(None), wis.implicit_collection_jobs_id.is_(None), step_states)
        .exists(),
    ]
    if JobState.NEW in states:
        clauses.append(~select(wis.id).where(step_of_invocation).exists())
    return or_(*clauses)


def invocation_state_predicate(states: list[str]) -> ColumnElement[bool]:
    """Invocations in one of ``states``; an unset state shows as ``new``."""
    predicate: ColumnElement[bool] = WorkflowInvocation.state.in_(states)
    if InvocationState.NEW in states:
        predicate = or_(predicate, WorkflowInvocation.state.is_(None))
    return predicate


def submission_state_predicate(states: list[str]) -> ColumnElement[bool]:
    """A plain job matches on its state, a mapped batch on its summary state."""
    icjja = ImplicitCollectionJobsJobAssociation
    plain_job = and_(icjja.implicit_collection_jobs_id.is_(None), Job.state.in_(states))
    # tool runs only reach batches through their jobs, so never an empty one
    return or_(plain_job, _batch_state_predicate(icjja.implicit_collection_jobs_id, None, states))


def _batch_state_predicate(
    icj_id: InstrumentedAttribute[Any], populated_state: InstrumentedAttribute[Any] | None, states: list[str]
) -> ColumnElement[bool]:
    """A mapped batch whose summary state, as ``summary_state`` and ``EMPTY_BATCH_STATES`` show it, is in ``states``."""
    member = aliased(ImplicitCollectionJobsJobAssociation)
    member_job = aliased(Job)
    rank_whens: list[tuple[ColumnElement[bool], int]] = [
        (member_job.state.in_([state.value for state in group]), rank)
        for rank, (_, group) in enumerate(SUMMARY_STATE_GROUPS)
    ]
    rank_whens.append((member_job.state == JobState.SKIPPED.value, SUMMARY_SKIPPED_RANK))
    summary_rank = (
        select(func.min(case(*rank_whens, else_=SUMMARY_OK_RANK)))
        .select_from(member)
        .join(member_job, member_job.id == member.job_id)
        .where(member.implicit_collection_jobs_id == icj_id)
        .scalar_subquery()
    )
    clauses: list[ColumnElement[bool]] = [summary_rank.in_(summary_ranks(states))]
    if populated_state is not None:
        empty_states = [populated for populated, state in EMPTY_BATCH_STATES.items() if state in states]
        shown: ColumnElement[bool] = populated_state.in_(empty_states)
        if JobState.NEW in states:
            shown = or_(shown, populated_state.is_(None), populated_state.not_in(list(EMPTY_BATCH_STATES)))
        clauses.append(and_(summary_rank.is_(None), shown))
    return or_(*clauses)


def invoked_workflows_stmt(user_id: int, workflow_ids: Collection[int]) -> Select[tuple[int]]:
    """Each invocation by the user of one of ``workflow_ids``, as its workflow id."""
    return _user_invocations(user_id, workflow_ids, WorkflowInvocation.workflow_id)


def invocations_stmt(user_id: int, workflow_ids: Collection[int]) -> Select[Any]:
    """The user's invocations of ``workflow_ids`` with their history, as ``InvocationPageRow`` columns."""
    return _user_invocations(
        user_id,
        workflow_ids,
        WorkflowInvocation.id,
        WorkflowInvocation.workflow_id,
        WorkflowInvocation.state,
        WorkflowInvocation.create_time,
        WorkflowInvocation.update_time,
        History.id,
        History.name,
        History.deleted,
        History.purged,
    )


def _user_invocations(user_id: int, workflow_ids: Collection[int], *columns: Any) -> Select[Any]:
    return (
        select(*columns)
        .join(History, History.id == WorkflowInvocation.history_id)
        .where(WorkflowInvocation.workflow_id.in_(workflow_ids), History.user_id == user_id)
    )


def tool_submissions_stmt(predicates: list[ColumnElement[bool]], query: ToolRunsQuery) -> Select[Any]:
    """One row per submission of ``query``'s filters, a mapped batch by its first job, as ``ToolRunPageRow`` columns."""
    icjja = ImplicitCollectionJobsJobAssociation
    sibling = aliased(ImplicitCollectionJobsJobAssociation)
    earlier_sibling = (
        select(sibling.id)
        .where(
            sibling.implicit_collection_jobs_id == icjja.implicit_collection_jobs_id,
            or_(
                sibling.order_index < icjja.order_index,
                and_(sibling.order_index == icjja.order_index, sibling.job_id < icjja.job_id),
            ),
        )
        .exists()
    )
    stmt = (
        select(
            Job.id,
            icjja.implicit_collection_jobs_id,
            Job.create_time,
            Job.update_time,
            History.id,
            History.name,
            History.deleted,
            History.purged,
        )
        .join(History, History.id == Job.history_id)
        .outerjoin(icjja, icjja.job_id == Job.id)
        .where(*predicates, ~earlier_sibling)
    )
    if query.tool_versions:
        stmt = stmt.where(Job.tool_version.in_(query.tool_versions))
    if query.history_id is not None:
        stmt = stmt.where(Job.history_id == query.history_id)
    if query.states:
        stmt = stmt.where(submission_state_predicate(query.states))
    if not query.include_workflow_jobs:
        wis = WorkflowInvocationStep
        in_workflow = (
            select(wis.id)
            .where(or_(wis.job_id == Job.id, wis.implicit_collection_jobs_id == icjja.implicit_collection_jobs_id))
            .exists()
        )
        stmt = stmt.where(~in_workflow)
    return stmt


def tool_versions_stmt(predicates: list[ColumnElement[bool]]) -> Select[Any]:
    """Distinct tool versions the jobs matching ``predicates`` ran."""
    return select(Job.tool_version).where(*predicates, Job.tool_version.is_not(None)).distinct()


def output_labels_stmt(workflow_ids: Collection[int] | Select[Any]) -> Select[Any]:
    """Labelled outputs of the given Workflows as (workflow id, label), in step order."""
    return (
        select(WorkflowStep.workflow_id, WorkflowOutput.label)
        .join(WorkflowStep, WorkflowStep.id == WorkflowOutput.workflow_step_id)
        .where(WorkflowStep.workflow_id.in_(workflow_ids), WorkflowOutput.label.is_not(None))
        .order_by(WorkflowStep.order_index, WorkflowOutput.id)
    )


def tool_predicates(user_id: int, tool_id: str) -> list[ColumnElement[bool]]:
    """The user's jobs of a tool at any version; a Tool Shed id matches its versioned guids."""
    base = versionless_tool_id(tool_id)
    return [Job.user_id == user_id, or_(Job.tool_id == base, Job.tool_id.startswith(f"{base}/", autoescape=True))]
