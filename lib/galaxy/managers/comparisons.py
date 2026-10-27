"""Resolve comparison tables of runs across workflow invocations."""

from collections import defaultdict
from collections.abc import Collection
from datetime import datetime
from typing import (
    Any,
    NamedTuple,
)

from sqlalchemy import (
    and_,
    or_,
    select,
)
from sqlalchemy.orm import InstrumentedAttribute
from sqlalchemy.sql.elements import ColumnElement

from galaxy.exceptions import ObjectNotFound
from galaxy.managers.comparison_cells import (
    ComparisonAccess,
    ComparisonCellBuilder,
    ImplicitCollectionJobsRecord,
    ItemRef,
    JobRecord,
)
from galaxy.managers.comparison_columns import (
    align_columns,
    ColumnSpec,
    missing_reason,
    normalize_io_name,
    reused_state,
    summary_state,
)
from galaxy.managers.workflows import get_count
from galaxy.model import (
    History,
    ImplicitCollectionJobsJobAssociation,
    Job,
    Workflow,
    WorkflowInvocation,
    WorkflowInvocationStep,
    WorkflowInvocationStepOutputDatasetAssociation,
    WorkflowInvocationStepOutputDatasetCollectionAssociation,
    WorkflowInvocationToSubworkflowInvocationAssociation,
    WorkflowStep,
)
from galaxy.model.scoped_session import galaxy_scoped_session
from galaxy.schema.comparisons import (
    AnyComparisonCell,
    ComparisonColumn,
    ComparisonQueryBase,
    ComparisonRow,
    ComparisonTable,
    HistoryRef,
    ImplicitCollectionJobsRunRef,
    InvocationRunRef,
    JobRunRef,
    MissingCell,
    ReusedState,
    StepRunsQuery,
)
from galaxy.schema.states import DatasetCollectionPopulatedState


class InvocationPageRow(NamedTuple):
    id: int
    workflow_id: int
    state: str | None
    create_time: datetime
    update_time: datetime
    history_id: int
    history_name: str | None
    history_deleted: bool
    history_purged: bool


class InvocationStepRecord(NamedTuple):
    id: int
    workflow_invocation_id: int
    state: str | None
    job_id: int | None
    implicit_collection_jobs_id: int | None


class ComparisonsManager:
    def __init__(self, sa_session: galaxy_scoped_session, cell_builder: ComparisonCellBuilder):
        self.sa_session = sa_session
        self.cell_builder = cell_builder

    def step_runs(
        self, access: ComparisonAccess, stored_workflow_id: int, query: StepRunsQuery
    ) -> tuple[ComparisonTable, int]:
        """One row per invocation of the versions with a step labelled ``query.step_label``."""
        stmt = (
            select(WorkflowStep.id, WorkflowStep.workflow_id)
            .join(Workflow, Workflow.id == WorkflowStep.workflow_id)
            .where(Workflow.stored_workflow_id == stored_workflow_id, WorkflowStep.label == query.step_label)
        )
        step_ids_by_workflow = {workflow_id: step_id for step_id, workflow_id in self.sa_session.execute(stmt)}
        if not step_ids_by_workflow:
            raise ObjectNotFound(f"No version of this workflow has a step labelled [{query.step_label}].")
        step_ids = list(step_ids_by_workflow.values())
        state_predicate = _step_state_predicate(step_ids, query.states) if query.states else None
        page, total = self._page_invocations(access.user_id, list(step_ids_by_workflow), query, state_predicate)
        columns, rows = self._step_rows(access, page, step_ids, query, self._version_map(stored_workflow_id))
        return ComparisonTable(query=query, columns=columns, rows=rows), total

    def _version_map(self, stored_workflow_id: int) -> dict[int, int]:
        """0-based version of each Workflow of a StoredWorkflow, as ``StoredWorkflow.version_of`` numbers them."""
        stmt = select(Workflow.id).where(Workflow.stored_workflow_id == stored_workflow_id).order_by(Workflow.id)
        return {workflow_id: version for version, workflow_id in enumerate(self.sa_session.scalars(stmt))}

    def _page_invocations(
        self,
        user_id: int,
        workflow_ids: Collection[int],
        query: ComparisonQueryBase,
        state_predicate: ColumnElement[bool] | None,
    ) -> tuple[list[InvocationPageRow], int]:
        stmt = (
            select(
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
            .join(History, History.id == WorkflowInvocation.history_id)
            .where(WorkflowInvocation.workflow_id.in_(workflow_ids), History.user_id == user_id)
        )
        if state_predicate is not None:
            stmt = stmt.where(state_predicate)
        total = get_count(self.sa_session, stmt)
        # create_time is unindexed; id order matches it
        order_by: list[InstrumentedAttribute[Any]] = [WorkflowInvocation.id]
        if query.sort_by == "update_time":
            order_by.insert(0, WorkflowInvocation.update_time)
        stmt = stmt.order_by(*(column.desc() if query.sort_desc else column.asc() for column in order_by))
        stmt = stmt.limit(query.limit).offset(query.offset)
        return [InvocationPageRow(*row) for row in self.sa_session.execute(stmt)], total

    def _step_rows(
        self,
        access: ComparisonAccess,
        page: list[InvocationPageRow],
        step_ids: list[int],
        query: StepRunsQuery,
        version_map: dict[int, int],
    ) -> tuple[list[ComparisonColumn], list[ComparisonRow]]:
        invocation_ids = [invocation.id for invocation in page]
        steps = self._invocation_steps(invocation_ids, step_ids)
        outputs = self._step_outputs([step.id for step in steps.values()])
        jobs = self.cell_builder.load_jobs({step.job_id for step in steps.values() if step.job_id})
        icjs = self.cell_builder.load_implicit_collection_jobs(
            {step.implicit_collection_jobs_id for step in steps.values() if step.implicit_collection_jobs_id}
        )
        job_inputs = self.cell_builder.job_inputs(
            [*jobs, *(icj.representative.id for icj in icjs.values() if icj.representative)]
        )
        icj_inputs = self.cell_builder.implicit_collection_inputs(list(icjs))
        subworkflow_invocations = self._subworkflow_invocations(invocation_ids, step_ids)

        io_by_invocation: dict[int, dict[str, ItemRef]] = {}
        declared: dict[int, dict[str, ColumnSpec]] = defaultdict(dict)
        for invocation in page:
            version = version_map[invocation.workflow_id]
            step = steps.get(invocation.id)
            io: dict[str, ItemRef] = {}
            if step:
                job = jobs.get(step.job_id) if step.job_id else None
                icj = icjs.get(step.implicit_collection_jobs_id) if step.implicit_collection_jobs_id else None
                inputs = {}
                if job:
                    inputs = job_inputs.get(job.id, {})
                elif icj:
                    representative_inputs = job_inputs.get(icj.representative.id, {}) if icj.representative else {}
                    inputs = {**representative_inputs, **icj_inputs.get(icj.id, {})}
                io.update(_keyed("input", inputs))
                io.update(_keyed("output", outputs.get(step.id, {})))
            io_by_invocation[invocation.id] = io
            for key in io:
                role, name = key.split(":", 1)
                declared[version].setdefault(
                    key, ColumnSpec(key=key, label=name, role="input" if role == "input" else "output")
                )

        newest_version = max(declared) if declared else 0
        columns = align_columns({v: list(specs.values()) for v, specs in declared.items()}, newest_version)
        item_cells = self.cell_builder.item_cells(
            (ref for io in io_by_invocation.values() for ref in io.values()),
            access,
            query.metadata_elements,
            query.inline_expression_values,
        )
        metadata_keys: dict[str, set[str]] = defaultdict(set)
        rows = []
        for invocation in page:
            version = version_map[invocation.workflow_id]
            step = steps.get(invocation.id)
            job = jobs.get(step.job_id) if step and step.job_id else None
            icj = icjs.get(step.implicit_collection_jobs_id) if step and step.implicit_collection_jobs_id else None
            state = _step_state(step, job, icj)
            representative = job or (icj.representative if icj else None)
            terminal = state not in Job.non_ready_states
            cells: dict[str, AnyComparisonCell] = {}
            io = io_by_invocation[invocation.id]
            for column in columns:
                ref = io.get(column.key)
                item_cell = item_cells.get(ref) if ref else None
                if item_cell:
                    cells[column.key] = item_cell.cell
                    metadata_keys[column.key].update(item_cell.metadata_keys)
                else:
                    # a version's columns are only known from its scheduled steps on this page
                    column_in_version = step is None or column.key in declared.get(version, ())
                    reason = missing_reason(column_in_version, (step.state or "new") if step else None, state, terminal)
                    cells[column.key] = MissingCell(reason=reason)
            rows.append(
                ComparisonRow(
                    run=InvocationRunRef(id=invocation.id, state=invocation.state or "new"),
                    step_job=_step_job_ref(job, icj),
                    subworkflow_invocation_id=subworkflow_invocations.get(invocation.id),
                    create_time=invocation.create_time,
                    update_time=invocation.update_time,
                    state=state,
                    version=version,
                    tool_id=representative.tool_id if representative else None,
                    tool_version=representative.tool_version if representative else None,
                    reused=_reused(job, icj),
                    history=HistoryRef(
                        id=invocation.history_id,
                        name=invocation.history_name,
                        deleted=invocation.history_deleted,
                        purged=invocation.history_purged,
                    ),
                    cells=cells,
                )
            )
        for column in columns:
            column.metadata_keys = sorted(metadata_keys[column.key])
        return columns, rows

    def _invocation_steps(self, invocation_ids: list[int], step_ids: list[int]) -> dict[int, InvocationStepRecord]:
        if not invocation_ids:
            return {}
        wis = WorkflowInvocationStep
        stmt = (
            select(wis.id, wis.workflow_invocation_id, wis.state, wis.job_id, wis.implicit_collection_jobs_id)
            .where(wis.workflow_invocation_id.in_(invocation_ids), wis.workflow_step_id.in_(step_ids))
            .order_by(wis.id)
        )
        steps: dict[int, InvocationStepRecord] = {}
        for row in self.sa_session.execute(stmt):
            step = InvocationStepRecord(*row)
            steps.setdefault(step.workflow_invocation_id, step)
        return steps

    def _step_outputs(self, invocation_step_ids: list[int]) -> dict[int, dict[str, ItemRef]]:
        outputs: dict[int, dict[str, ItemRef]] = defaultdict(dict)
        if not invocation_step_ids:
            return outputs
        dataset_assoc = WorkflowInvocationStepOutputDatasetAssociation
        stmt = (
            select(dataset_assoc.workflow_invocation_step_id, dataset_assoc.output_name, dataset_assoc.dataset_id)
            .where(
                dataset_assoc.workflow_invocation_step_id.in_(invocation_step_ids),
                dataset_assoc.dataset_id.is_not(None),
            )
            .order_by(dataset_assoc.id)
        )
        for step_id, name, hda_id in self.sa_session.execute(stmt):
            outputs[step_id][name] = ItemRef("hda", hda_id)
        collection_assoc = WorkflowInvocationStepOutputDatasetCollectionAssociation
        stmt = (
            select(
                collection_assoc.workflow_invocation_step_id,
                collection_assoc.output_name,
                collection_assoc.dataset_collection_id,
            )
            .where(
                collection_assoc.workflow_invocation_step_id.in_(invocation_step_ids),
                collection_assoc.dataset_collection_id.is_not(None),
            )
            .order_by(collection_assoc.id)
        )
        for step_id, name, hdca_id in self.sa_session.execute(stmt):
            outputs[step_id][name] = ItemRef("hdca", hdca_id)
        return outputs

    def _subworkflow_invocations(self, invocation_ids: list[int], step_ids: list[int]) -> dict[int, int]:
        if not invocation_ids:
            return {}
        assoc = WorkflowInvocationToSubworkflowInvocationAssociation
        stmt = select(assoc.workflow_invocation_id, assoc.subworkflow_invocation_id).where(
            assoc.workflow_invocation_id.in_(invocation_ids),
            assoc.workflow_step_id.in_(step_ids),
            assoc.subworkflow_invocation_id.is_not(None),
        )
        subworkflow_invocations: dict[int, int] = {}
        for invocation_id, subworkflow_invocation_id in self.sa_session.execute(stmt):
            subworkflow_invocations[invocation_id] = subworkflow_invocation_id
        return subworkflow_invocations


def _step_state_predicate(step_ids: list[int], states: list[str]) -> ColumnElement[bool]:
    """Invocations whose compared step is in one of ``states``; a step not scheduled yet counts as ``new``."""
    wis = WorkflowInvocationStep
    icjja = ImplicitCollectionJobsJobAssociation
    step_of_invocation = and_(wis.workflow_invocation_id == WorkflowInvocation.id, wis.workflow_step_id.in_(step_ids))
    clauses: list[ColumnElement[bool]] = [
        select(wis.id).join(Job, Job.id == wis.job_id).where(step_of_invocation, Job.state.in_(states)).exists(),
        select(wis.id)
        .join(icjja, icjja.implicit_collection_jobs_id == wis.implicit_collection_jobs_id)
        .join(Job, Job.id == icjja.job_id)
        .where(step_of_invocation, Job.state.in_(states))
        .exists(),
        select(wis.id)
        .where(
            step_of_invocation,
            wis.job_id.is_(None),
            wis.implicit_collection_jobs_id.is_(None),
            wis.state.in_(states),
        )
        .exists(),
    ]
    if "new" in states:
        clauses.append(~select(wis.id).where(step_of_invocation).exists())
    return or_(*clauses)


def _keyed(role: str, items: dict[str, ItemRef]) -> dict[str, ItemRef]:
    """Role-prefix normalized io names; an exact name wins over names folded into it."""
    keyed: dict[str, ItemRef] = {}
    for name, ref in items.items():
        normalized = normalize_io_name(name)
        key = f"{role}:{normalized}"
        if normalized == name:
            keyed[key] = ref
        else:
            keyed.setdefault(key, ref)
    return keyed


def _step_state(
    step: InvocationStepRecord | None, job: JobRecord | None, icj: ImplicitCollectionJobsRecord | None
) -> str:
    if job:
        return job.state
    if icj:
        return summary_state(icj.states) if icj.job_count else _empty_batch_state(icj.populated_state)
    if step and step.state:
        return step.state
    return "new"


def _step_job_ref(
    job: JobRecord | None, icj: ImplicitCollectionJobsRecord | None
) -> JobRunRef | ImplicitCollectionJobsRunRef | None:
    if job:
        return JobRunRef(id=job.id, state=job.state)
    if icj:
        return ImplicitCollectionJobsRunRef(
            model="ImplicitCollectionJobs",
            id=icj.id,
            populated_state=icj.populated_state,
            representative_job_id=icj.representative.id if icj.representative else None,
            job_count=icj.job_count,
            states=icj.states,
        )
    return None


def _empty_batch_state(populated_state: str) -> str:
    """Row state of a mapped batch without jobs, e.g. mapped over an empty collection."""
    if populated_state == DatasetCollectionPopulatedState.OK:
        return Job.states.OK.value
    if populated_state == DatasetCollectionPopulatedState.FAILED:
        return Job.states.ERROR.value
    return Job.states.NEW.value


def _reused(job: JobRecord | None, icj: ImplicitCollectionJobsRecord | None) -> ReusedState | None:
    if job:
        return reused_state(int(job.copied), 1)
    if icj and icj.job_count:
        return reused_state(icj.copied_count, icj.job_count)
    return None
