"""Resolve comparison tables of runs across workflow invocations."""

from collections import defaultdict
from collections.abc import (
    Callable,
    Collection,
    Container,
    Iterable,
    Iterator,
    Mapping,
)
from datetime import datetime
from typing import (
    Any,
    NamedTuple,
    TypeAlias,
    TypeVar,
)

from sqlalchemy import (
    and_,
    case,
    func,
    or_,
    Row,
    select,
    Select,
)
from sqlalchemy.orm import (
    aliased,
    InstrumentedAttribute,
)
from sqlalchemy.sql.elements import ColumnElement

from galaxy.exceptions import ObjectNotFound
from galaxy.managers.comparison_cells import (
    ComparisonAccess,
    ComparisonCellBuilder,
    ImplicitCollectionJobsRecord,
    ItemCell,
    ItemRef,
    ItemRefs,
    JobRecord,
)
from galaxy.managers.comparison_columns import (
    align_columns,
    ColumnSpec,
    missing_reason,
    normalize_io_name,
    reused_state,
    SUMMARY_OK_RANK,
    summary_ranks,
    SUMMARY_SKIPPED_RANK,
    summary_state,
    SUMMARY_STATE_GROUPS,
)
from galaxy.managers.workflows import get_count
from galaxy.model import (
    History,
    ImplicitCollectionJobs,
    ImplicitCollectionJobsJobAssociation,
    Job,
    Workflow,
    WorkflowInvocation,
    WorkflowInvocationOutputDatasetAssociation,
    WorkflowInvocationOutputDatasetCollectionAssociation,
    WorkflowInvocationOutputValue,
    WorkflowInvocationStep,
    WorkflowInvocationStepOutputDatasetAssociation,
    WorkflowInvocationStepOutputDatasetCollectionAssociation,
    WorkflowInvocationToSubworkflowInvocationAssociation,
    WorkflowOutput,
    WorkflowRequestInputStepParameter,
    WorkflowRequestToInputDatasetAssociation,
    WorkflowRequestToInputDatasetCollectionAssociation,
    WorkflowStep,
    WorkflowStepInput,
)
from galaxy.model.scoped_session import galaxy_scoped_session
from galaxy.schema.comparisons import (
    AnyComparisonCell,
    ComparisonColumn,
    ComparisonColumnRole,
    ComparisonQueryBase,
    ComparisonRow,
    ComparisonTable,
    DatasetListCell,
    HistoryRef,
    ImplicitCollectionJobsRunRef,
    InvocationRunRef,
    JobRunRef,
    MissingCell,
    MissingReason,
    OutputRunsQuery,
    ReusedState,
    StepRunsQuery,
    ToolRunsQuery,
    ValueCell,
    WorkflowRunVia,
)
from galaxy.schema.states import (
    DatasetCollectionPopulatedState,
    InvocationState,
    JobState,
)
from galaxy.tool_util.version import parse_tool_version
from galaxy.util.tool_version import versionless_tool_id

INPUT_STEP_TYPES = ("data_input", "data_collection_input", "parameter_input")
IoValue: TypeAlias = ItemRef | ItemRefs | AnyComparisonCell
IoValueT = TypeVar("IoValueT")
NOT_SCHEDULED_INVOCATION_STATES = (
    InvocationState.NEW,
    InvocationState.READY,
    InvocationState.REQUIRES_MATERIALIZATION,
)
# row state of a mapped batch without jobs, e.g. mapped over an empty collection; others are new
EMPTY_BATCH_STATES = {
    DatasetCollectionPopulatedState.OK.value: JobState.OK.value,
    DatasetCollectionPopulatedState.FAILED.value: JobState.ERROR.value,
}


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


class ToolRunPageRow(NamedTuple):
    job_id: int
    implicit_collection_jobs_id: int | None
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
    action: Any


class ComparisonsManager:
    def __init__(self, sa_session: galaxy_scoped_session, cell_builder: ComparisonCellBuilder):
        self.sa_session = sa_session
        self.cell_builder = cell_builder

    def step_runs(
        self, access: ComparisonAccess, stored_workflow_id: int, query: StepRunsQuery
    ) -> tuple[ComparisonTable, int]:
        """One row per invocation of the versions with a step labelled ``query.step_label``."""
        stmt = (
            select(WorkflowStep.id, WorkflowStep.workflow_id, WorkflowStep.type)
            .join(Workflow, Workflow.id == WorkflowStep.workflow_id)
            .where(Workflow.stored_workflow_id == stored_workflow_id, WorkflowStep.label == query.step_label)
        )
        steps_by_workflow = {
            workflow_id: (step_id, step_type) for step_id, workflow_id, step_type in self.sa_session.execute(stmt)
        }
        if not steps_by_workflow:
            raise ObjectNotFound(f"No version of this workflow has a step labelled [{query.step_label}].")
        step_ids = [step_id for step_id, _ in steps_by_workflow.values()]
        step_types = {workflow_id: step_type for workflow_id, (_, step_type) in steps_by_workflow.items()}
        state_predicate = _step_state_predicate(step_ids, query.states) if query.states else None
        version_map = self._version_map(stored_workflow_id)
        workflow_ids = _selected_versions({wid: version_map[wid] for wid in steps_by_workflow}, query.versions)
        page, total = self._page_invocations(access.user_id, workflow_ids, query, state_predicate)
        step_by_workflow = {workflow_id: step_id for workflow_id, (step_id, _) in steps_by_workflow.items()}
        columns, rows = self._step_rows(access, page, step_by_workflow, step_types, query, version_map)
        invoked = self.sa_session.scalars(_invoked_workflows_stmt(access.user_id, steps_by_workflow).distinct())
        versions_available = sorted(version_map[workflow_id] for workflow_id in invoked)
        table = ComparisonTable(query=query, columns=columns, rows=rows, versions_available=versions_available)
        return table, total

    def output_runs(
        self, access: ComparisonAccess, stored_workflow_id: int, query: OutputRunsQuery
    ) -> tuple[ComparisonTable, int]:
        """One row per invocation of any version, with labelled workflow inputs and outputs as columns."""
        version_map = self._version_map(stored_workflow_id)
        state_predicate = WorkflowInvocation.state.in_(query.states) if query.states else None
        workflow_ids = _selected_versions(version_map, query.versions)
        page, total = self._page_invocations(access.user_id, workflow_ids, query, state_predicate)
        columns, rows = self._output_rows(access, page, query, version_map)
        output_labels = self._invoked_output_labels(access.user_id, version_map)
        invoked = self.sa_session.scalars(_invoked_workflows_stmt(access.user_id, version_map).distinct())
        table = ComparisonTable(
            query=query,
            columns=columns,
            rows=rows,
            output_labels_available=output_labels,
            versions_available=sorted(version_map[workflow_id] for workflow_id in invoked),
        )
        return table, total

    def _invoked_output_labels(self, user_id: int, version_map: dict[int, int]) -> list[str]:
        """Output labels of every version the user has invoked, newest version first, then step order."""
        labels: dict[int, list[str]] = defaultdict(list)
        invoked = _invoked_workflows_stmt(user_id, version_map)
        for workflow_id, label in self.sa_session.execute(_output_labels_stmt(invoked)):
            labels[workflow_id].append(label)
        newest_first = sorted(labels, key=version_map.__getitem__, reverse=True)
        return list(dict.fromkeys(label for workflow_id in newest_first for label in labels[workflow_id]))

    def _output_rows(
        self,
        access: ComparisonAccess,
        page: list[InvocationPageRow],
        query: OutputRunsQuery,
        version_map: dict[int, int],
    ) -> tuple[list[ComparisonColumn], list[ComparisonRow]]:
        declared = self._declared_workflow_io({invocation.workflow_id for invocation in page})
        if query.output_labels is not None:
            labels = set(query.output_labels)
            declared = {
                wid: [spec for spec in specs if spec.role != "output" or spec.label in labels]
                for wid, specs in declared.items()
            }
        # every version on the page counts, labelled io or not
        declared_by_version: dict[int, list[ColumnSpec]] = {version_map[i.workflow_id]: [] for i in page}
        declared_by_version.update((version_map[wid], specs) for wid, specs in declared.items())
        newest_version = max(declared_by_version) if declared_by_version else 0
        columns = align_columns(declared_by_version, newest_version)
        column_keys = {column.key for column in columns}
        io_by_invocation = {
            invocation_id: {key: value for key, value in io.items() if key in column_keys}
            for invocation_id, io in self._invocation_io([invocation.id for invocation in page]).items()
        }
        item_cells = self.cell_builder.item_cells(
            _item_refs(io_by_invocation.values()),
            access,
            query.metadata_elements,
            query.inline_expression_values,
        )
        metadata_keys: dict[str, set[str]] = defaultdict(set)
        rows = []
        for invocation in page:
            version = version_map[invocation.workflow_id]
            state = invocation.state or InvocationState.NEW.value
            in_version = {spec.key for spec in declared_by_version.get(version, ())}
            scheduled = state not in NOT_SCHEDULED_INVOCATION_STATES
            reason = missing_reason(True, state if scheduled else None, None, True)
            io = io_by_invocation.get(invocation.id, {})
            cells = _cells(columns, io, item_cells, metadata_keys, in_version, reason)
            rows.append(
                ComparisonRow(
                    run=InvocationRunRef(id=invocation.id, state=state),
                    create_time=invocation.create_time,
                    update_time=invocation.update_time,
                    state=state,
                    version=version,
                    history=_history_ref(invocation),
                    cells=cells,
                )
            )
        _set_metadata_keys(columns, metadata_keys)
        return columns, rows

    def _declared_workflow_io(self, workflow_ids: Collection[int]) -> dict[int, list[ColumnSpec]]:
        """Labelled input steps then labelled outputs of each Workflow, in step order; duplicates kept."""
        declared: dict[int, list[ColumnSpec]] = defaultdict(list)
        if not workflow_ids:
            return declared
        input_stmt = (
            select(WorkflowStep.workflow_id, WorkflowStep.label, WorkflowStep.type)
            .where(
                WorkflowStep.workflow_id.in_(workflow_ids),
                WorkflowStep.type.in_(INPUT_STEP_TYPES),
                WorkflowStep.label.is_not(None),
            )
            .order_by(WorkflowStep.order_index, WorkflowStep.id)
        )
        for workflow_id, label, step_type in self.sa_session.execute(input_stmt):
            role: ComparisonColumnRole = "parameter" if step_type == "parameter_input" else "input"
            declared[workflow_id].append(ColumnSpec(key=f"{role}:{label}", label=label, role=role))
        for workflow_id, label in self.sa_session.execute(_output_labels_stmt(workflow_ids)):
            declared[workflow_id].append(ColumnSpec(key=f"output:{label}", label=label, role="output"))
        return declared

    def _invocation_io(self, invocation_ids: list[int]) -> dict[int, dict[str, ItemRef | AnyComparisonCell]]:
        """Labelled inputs, parameters and outputs of each invocation; the first output by id wins a label."""
        io = self._request_inputs(invocation_ids)
        if not invocation_ids:
            return io
        output_sources: list[tuple[Any, Callable[[Any], ItemRef | AnyComparisonCell]]] = [
            (WorkflowInvocationOutputDatasetAssociation.dataset_id, lambda v: ItemRef("hda", v)),
            (WorkflowInvocationOutputDatasetCollectionAssociation.dataset_collection_id, _hdca_ref),
            (WorkflowInvocationOutputValue.value, _output_value_cell),
        ]
        outputs: dict[tuple[int, str], tuple[int, ItemRef | AnyComparisonCell]] = {}
        for value_column, to_value in output_sources:
            assoc = value_column.class_
            stmt = (
                select(assoc.workflow_invocation_id, WorkflowOutput.id, WorkflowOutput.label, value_column)
                .join(WorkflowOutput, WorkflowOutput.id == assoc.workflow_output_id)
                .where(assoc.workflow_invocation_id.in_(invocation_ids), WorkflowOutput.label.is_not(None))
            )
            for invocation_id, output_id, label, value in self.sa_session.execute(stmt):
                if value is None and to_value is not _output_value_cell:
                    continue
                output_key = (invocation_id, f"output:{label}")
                if output_key not in outputs or output_id < outputs[output_key][0]:
                    outputs[output_key] = (output_id, to_value(value))
        for (invocation_id, column_key), (_, output_value) in outputs.items():
            io[invocation_id][column_key] = output_value
        return io

    def _request_inputs(
        self, invocation_ids: list[int], step_ids: Collection[int] | None = None
    ) -> dict[int, dict[str, ItemRef | AnyComparisonCell]]:
        """Labelled input steps' datasets, collections and values each invocation was requested with."""
        inputs: dict[int, dict[str, ItemRef | AnyComparisonCell]] = defaultdict(dict)
        if not invocation_ids:
            return inputs
        sources: list[tuple[Any, str, Callable[[Any], ItemRef | AnyComparisonCell]]] = [
            (WorkflowRequestToInputDatasetAssociation.dataset_id, "input", lambda v: ItemRef("hda", v)),
            (WorkflowRequestToInputDatasetCollectionAssociation.dataset_collection_id, "input", _hdca_ref),
            (WorkflowRequestInputStepParameter.parameter_value, "parameter", _parameter_cell),
        ]
        for value_column, role, to_value in sources:
            assoc = value_column.class_
            stmt = (
                select(assoc.workflow_invocation_id, WorkflowStep.label, value_column)
                .join(WorkflowStep, WorkflowStep.id == assoc.workflow_step_id)
                .where(assoc.workflow_invocation_id.in_(invocation_ids), WorkflowStep.label.is_not(None))
                .order_by(assoc.id)
            )
            if step_ids is not None:
                stmt = stmt.where(assoc.workflow_step_id.in_(step_ids))
            for invocation_id, label, value in self.sa_session.execute(stmt):
                if role == "input" and value is None:
                    continue
                inputs[invocation_id].setdefault(f"{role}:{label}", to_value(value))
        return inputs

    def tool_runs(self, access: ComparisonAccess, query: ToolRunsQuery) -> tuple[ComparisonTable, int]:
        """One row per submission of a tool: a plain job, or a mapped batch shown by its first job."""
        tool_predicates = _tool_predicates(access.user_id, query.tool_id)
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
            .where(*tool_predicates, ~earlier_sibling)
        )
        if query.tool_versions:
            stmt = stmt.where(Job.tool_version.in_(query.tool_versions))
        if query.history_id is not None:
            stmt = stmt.where(Job.history_id == query.history_id)
        if query.states:
            stmt = stmt.where(_submission_state_predicate(query.states))
        if not query.include_workflow_jobs:
            wis = WorkflowInvocationStep
            in_workflow = (
                select(wis.id)
                .where(or_(wis.job_id == Job.id, wis.implicit_collection_jobs_id == icjja.implicit_collection_jobs_id))
                .exists()
            )
            stmt = stmt.where(~in_workflow)
        page_rows, total = self._count_and_page(stmt, Job.id, Job.update_time, query)
        page = [ToolRunPageRow(*row) for row in page_rows]
        columns, rows = self._tool_rows(access, page, query)
        table = ComparisonTable(
            query=query, columns=columns, rows=rows, tool_versions_available=self._tool_versions(tool_predicates)
        )
        return table, total

    def _tool_rows(
        self, access: ComparisonAccess, page: list[ToolRunPageRow], query: ToolRunsQuery
    ) -> tuple[list[ComparisonColumn], list[ComparisonRow]]:
        jobs = self.cell_builder.load_jobs([row.job_id for row in page if row.implicit_collection_jobs_id is None])
        icjs = self.cell_builder.load_implicit_collection_jobs(
            [row.implicit_collection_jobs_id for row in page if row.implicit_collection_jobs_id is not None]
        )
        job_inputs, icj_inputs = self._submission_inputs(jobs, icjs)
        job_outputs = self.cell_builder.job_outputs(list(jobs))
        icj_outputs = self.cell_builder.implicit_collection_outputs(list(icjs))
        via = self._workflow_runs_via(list(jobs), list(icjs))

        io_by_row: list[dict[str, IoValue]] = []
        specs: dict[str, ColumnSpec] = {}
        declared: dict[str | None, set[str]] = defaultdict(set)
        for row in page:
            icj_id = row.implicit_collection_jobs_id
            if icj_id is None:
                inputs, outputs = job_inputs.get(row.job_id, {}), job_outputs.get(row.job_id, {})
                tool_version = jobs[row.job_id].tool_version if row.job_id in jobs else None
            else:
                inputs, outputs = icj_inputs.get(icj_id, {}), icj_outputs.get(icj_id, {})
                representative = icjs[icj_id].representative if icj_id in icjs else None
                tool_version = representative.tool_version if representative else None
            io: dict[str, IoValue] = {**_keyed("input", inputs), **_keyed("output", outputs)}
            if icj_id is None:
                _mark_skipped_outputs(io, jobs.get(row.job_id))
            io_by_row.append(io)
            declared[tool_version].update(io)
            for key in io:
                specs.setdefault(key, _column_spec(key))
        columns = align_columns({0: list(specs.values())}, 0)
        item_cells = self.cell_builder.item_cells(
            _item_refs(io_by_row),
            access,
            query.metadata_elements,
            query.inline_expression_values,
        )
        metadata_keys: dict[str, set[str]] = defaultdict(set)
        rows = []
        for row, io in zip(page, io_by_row):
            icj_id = row.implicit_collection_jobs_id
            job = jobs.get(row.job_id) if icj_id is None else None
            icj = icjs.get(icj_id) if icj_id is not None else None
            representative = job or (icj.representative if icj else None)
            run = _step_job_ref(job, icj)
            # the loaders return every paged id, so total_matches and rows agree
            assert run is not None
            state = _step_state(None, job, icj)
            tool_version = representative.tool_version if representative else None
            reason = missing_reason(True, state, state, state not in Job.non_ready_states)
            # a tool version's columns are only known from its rows on this page
            cells = _cells(columns, io, item_cells, metadata_keys, declared[tool_version], reason)
            rows.append(
                ComparisonRow(
                    run=run,
                    via=via.get((icj_id is not None, icj_id if icj_id is not None else row.job_id)),
                    create_time=row.create_time,
                    update_time=row.update_time,
                    state=state,
                    tool_id=representative.tool_id if representative else None,
                    tool_version=tool_version,
                    reused=_reused(job, icj),
                    history=_history_ref(row),
                    cells=cells,
                )
            )
        _set_metadata_keys(columns, metadata_keys)
        return columns, rows

    def _workflow_runs_via(self, job_ids: list[int], icj_ids: list[int]) -> dict[tuple[bool, int], WorkflowRunVia]:
        """The invocation step that ran each job or mapped batch, keyed by (is_batch, id)."""
        if not job_ids and not icj_ids:
            return {}
        wis = WorkflowInvocationStep
        stmt = (
            select(
                wis.job_id,
                wis.implicit_collection_jobs_id,
                wis.workflow_invocation_id,
                WorkflowStep.label,
                Workflow.name,
            )
            .join(WorkflowStep, WorkflowStep.id == wis.workflow_step_id)
            .join(Workflow, Workflow.id == WorkflowStep.workflow_id)
            .where(or_(wis.job_id.in_(job_ids), wis.implicit_collection_jobs_id.in_(icj_ids)))
        )
        via: dict[tuple[bool, int], WorkflowRunVia] = {}
        for job_id, icj_id, invocation_id, step_label, workflow_name in self.sa_session.execute(stmt):
            key = (True, icj_id) if icj_id is not None else (False, job_id)
            via[key] = WorkflowRunVia(invocation_id=invocation_id, step_label=step_label, workflow_name=workflow_name)
        return via

    def _tool_versions(self, tool_predicates: list[ColumnElement[bool]]) -> list[str]:
        stmt = select(Job.tool_version).where(*tool_predicates, Job.tool_version.is_not(None)).distinct()
        return sorted(self.sa_session.scalars(stmt), key=parse_tool_version)

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
        page_rows, total = self._count_and_page(stmt, WorkflowInvocation.id, WorkflowInvocation.update_time, query)
        return [InvocationPageRow(*row) for row in page_rows], total

    def _count_and_page(
        self,
        stmt: Select[Any],
        id_column: InstrumentedAttribute[int],
        update_time_column: InstrumentedAttribute[datetime],
        query: ComparisonQueryBase,
    ) -> tuple[list[Row[Any]], int]:
        """Total matches of ``stmt`` and the requested page of it, in the query's sort order."""
        total = get_count(self.sa_session, stmt)
        # create_time is unindexed; id order matches it
        order_by: list[InstrumentedAttribute[Any]] = [id_column]
        if query.sort_by == "update_time":
            order_by.insert(0, update_time_column)
        stmt = stmt.order_by(*(column.desc() if query.sort_desc else column.asc() for column in order_by))
        return list(self.sa_session.execute(stmt.limit(query.limit).offset(query.offset))), total

    def _step_rows(
        self,
        access: ComparisonAccess,
        page: list[InvocationPageRow],
        step_by_workflow: dict[int, int],
        step_types: dict[int, str],
        query: StepRunsQuery,
        version_map: dict[int, int],
    ) -> tuple[list[ComparisonColumn], list[ComparisonRow]]:
        invocation_ids = [invocation.id for invocation in page]
        step_ids = list(step_by_workflow.values())
        steps = self._invocation_steps(invocation_ids, step_ids)
        outputs = self._step_outputs([step.id for step in steps.values()])
        jobs = self.cell_builder.load_jobs({step.job_id for step in steps.values() if step.job_id})
        icjs = self.cell_builder.load_implicit_collection_jobs(
            {step.implicit_collection_jobs_id for step in steps.values() if step.implicit_collection_jobs_id}
        )
        job_inputs, icj_inputs = self._submission_inputs(jobs, icjs)
        subworkflow_invocations = self._subworkflow_invocations(invocation_ids, step_ids)
        request_inputs = self._request_inputs(invocation_ids, step_ids)

        io_by_invocation: dict[int, dict[str, IoValue]] = {}
        declared: dict[int, dict[str, ColumnSpec]] = defaultdict(dict)
        for invocation in page:
            version = version_map[invocation.workflow_id]
            step = steps.get(invocation.id)
            # an input step's own input; its step output is the same item
            io: dict[str, IoValue] = dict(request_inputs.get(invocation.id, {}))
            is_input_step = step_types[invocation.workflow_id] in INPUT_STEP_TYPES
            if step and is_input_step and not io and "output" in outputs.get(step.id, {}):
                # a defaulted data input is recorded only as the step's output
                io[f"input:{query.step_label}"] = outputs[step.id]["output"]
            if step and not is_input_step:
                job = jobs.get(step.job_id) if step.job_id else None
                icj = icjs.get(step.implicit_collection_jobs_id) if step.implicit_collection_jobs_id else None
                inputs = job_inputs.get(job.id, {}) if job else icj_inputs.get(icj.id, {}) if icj else {}
                io.update(_keyed("input", inputs))
                io.update(_keyed("output", outputs.get(step.id, {})))
                _mark_skipped_outputs(io, job)
            io_by_invocation[invocation.id] = io
            for key in io:
                declared[version].setdefault(key, _column_spec(key))
        # a version's step definition also declares inputs its runs on this page left empty
        observed = list(dict.fromkeys(key for specs in declared.values() for key in specs))
        page_workflow_ids = {invocation.workflow_id for invocation in page}
        defined = self._defined_step_inputs([step_by_workflow[workflow_id] for workflow_id in page_workflow_ids])
        for workflow_id in page_workflow_ids:
            version_specs = declared[version_map[workflow_id]]
            step_defines = defined.get(step_by_workflow[workflow_id], set())
            # a version none of whose runs here recorded outputs yet may have any of them
            outputs_unknown = not any(key.startswith("output:") for key in version_specs)
            for key in observed:
                if key in step_defines or (outputs_unknown and key.startswith("output:")):
                    version_specs.setdefault(key, _column_spec(key))

        newest_version = max(declared) if declared else 0
        columns = align_columns({v: list(specs.values()) for v, specs in declared.items()}, newest_version)
        item_cells = self.cell_builder.item_cells(
            _item_refs(io_by_invocation.values()),
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
            reason = missing_reason(True, (step.state or "new") if step else None, state, terminal)
            # an input step's one column is in every version with the step
            in_version = None if step_types[invocation.workflow_id] in INPUT_STEP_TYPES else declared[version]
            cells = _cells(columns, io_by_invocation[invocation.id], item_cells, metadata_keys, in_version, reason)
            rows.append(
                ComparisonRow(
                    run=InvocationRunRef(id=invocation.id, state=invocation.state or "new"),
                    step_job=_step_job_ref(job, icj),
                    subworkflow_invocation_id=subworkflow_invocations.get(invocation.id),
                    step_type=step_types[invocation.workflow_id],
                    step_action=_review_action(step),
                    create_time=invocation.create_time,
                    update_time=invocation.update_time,
                    state=state,
                    version=version,
                    tool_id=representative.tool_id if representative else None,
                    tool_version=representative.tool_version if representative else None,
                    reused=_reused(job, icj),
                    history=_history_ref(invocation),
                    cells=cells,
                )
            )
        _set_metadata_keys(columns, metadata_keys)
        return columns, rows

    def _defined_step_inputs(self, step_ids: Collection[int]) -> dict[int, set[str]]:
        """Input column keys each step's definition connects."""
        defined: dict[int, set[str]] = defaultdict(set)
        if not step_ids:
            return defined
        stmt = select(WorkflowStepInput.workflow_step_id, WorkflowStepInput.name).where(
            WorkflowStepInput.workflow_step_id.in_(step_ids)
        )
        for step_id, name in self.sa_session.execute(stmt):
            if name:
                defined[step_id].add(f"input:{normalize_io_name(name)}")
        return defined

    def _submission_inputs(
        self, jobs: dict[int, JobRecord], icjs: dict[int, ImplicitCollectionJobsRecord]
    ) -> tuple[dict[int, dict[str, ItemRef | ItemRefs]], dict[int, dict[str, ItemRef | ItemRefs]]]:
        """Inputs by job id and by mapped batch id; a batch has its first job's inputs plus the mapped-over ones."""
        representatives = {icj.id: icj.representative.id for icj in icjs.values() if icj.representative}
        job_inputs = self.cell_builder.job_inputs([*jobs, *representatives.values()])
        mapped_inputs = self.cell_builder.implicit_collection_inputs(list(icjs))
        icj_inputs: dict[int, dict[str, ItemRef | ItemRefs]] = {
            icj_id: {
                **(job_inputs.get(representatives[icj_id], {}) if icj_id in representatives else {}),
                **mapped_inputs.get(icj_id, {}),
            }
            for icj_id in icjs
        }
        return job_inputs, icj_inputs

    def _invocation_steps(self, invocation_ids: list[int], step_ids: list[int]) -> dict[int, InvocationStepRecord]:
        if not invocation_ids:
            return {}
        wis = WorkflowInvocationStep
        stmt = (
            select(
                wis.id, wis.workflow_invocation_id, wis.state, wis.job_id, wis.implicit_collection_jobs_id, wis.action
            )
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


def _selected_versions(version_map: Mapping[int, int], versions: list[int] | None) -> list[int]:
    """Workflow ids of ``version_map`` whose 0-based version is in ``versions``; all of them for None."""
    return [workflow_id for workflow_id, version in version_map.items() if versions is None or version in versions]


def _step_state_predicate(step_ids: list[int], states: list[str]) -> ColumnElement[bool]:
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


def _batch_state_predicate(
    icj_id: InstrumentedAttribute[Any], populated_state: InstrumentedAttribute[Any] | None, states: list[str]
) -> ColumnElement[bool]:
    """A mapped batch whose summary state, as ``summary_state`` and ``EMPTY_BATCH_STATES`` show it, is in ``states``."""
    member = aliased(ImplicitCollectionJobsJobAssociation)
    member_job = aliased(Job)
    rank_whens = [
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


def _invoked_workflows_stmt(user_id: int, workflow_ids: Collection[int]) -> Select[tuple[int]]:
    """Each invocation by the user of one of ``workflow_ids``, as its workflow id."""
    return (
        select(WorkflowInvocation.workflow_id)
        .join(History, History.id == WorkflowInvocation.history_id)
        .where(WorkflowInvocation.workflow_id.in_(workflow_ids), History.user_id == user_id)
    )


def _output_labels_stmt(workflow_ids: Collection[int] | Select[Any]) -> Select[Any]:
    """Labelled outputs of the given Workflows as (workflow id, label), in step order."""
    return (
        select(WorkflowStep.workflow_id, WorkflowOutput.label)
        .join(WorkflowStep, WorkflowStep.id == WorkflowOutput.workflow_step_id)
        .where(WorkflowStep.workflow_id.in_(workflow_ids), WorkflowOutput.label.is_not(None))
        .order_by(WorkflowStep.order_index, WorkflowOutput.id)
    )


def _tool_predicates(user_id: int, tool_id: str) -> list[ColumnElement[bool]]:
    """The user's jobs of a tool at any version; a Tool Shed id matches its versioned guids."""
    base = versionless_tool_id(tool_id)
    return [Job.user_id == user_id, or_(Job.tool_id == base, Job.tool_id.startswith(f"{base}/", autoescape=True))]


def _submission_state_predicate(states: list[str]) -> ColumnElement[bool]:
    """A plain job matches on its state, a mapped batch on its summary state."""
    icjja = ImplicitCollectionJobsJobAssociation
    plain_job = and_(icjja.implicit_collection_jobs_id.is_(None), Job.state.in_(states))
    # tool runs only reach batches through their jobs, so never an empty one
    return or_(plain_job, _batch_state_predicate(icjja.implicit_collection_jobs_id, None, states))


def _hdca_ref(hdca_id: int) -> ItemRef:
    return ItemRef("hdca", hdca_id)


def _parameter_cell(value: Any) -> ValueCell:
    return ValueCell(value=value, source="parameter")


def _output_value_cell(value: Any) -> ValueCell | MissingCell:
    """A workflow output value; a skipped step's ``NoReplacement`` sentinel renders as skipped."""
    if isinstance(value, dict) and value.get("__class__") == "NoReplacement":
        return MissingCell(reason="skipped")
    return ValueCell(value=value, source="output_value")


def _cells(
    columns: list[ComparisonColumn],
    io: Mapping[str, IoValue],
    item_cells: Mapping[ItemRef, ItemCell],
    metadata_keys: dict[str, set[str]],
    in_version: Container[str] | None,
    reason: MissingReason,
) -> dict[str, AnyComparisonCell]:
    """One cell per column: the item's cell, a ready-made cell, or why it is missing.

    Columns not in ``in_version`` (None: unknown, assume present) are ``not_in_version``, other gaps ``reason``.
    """
    cells: dict[str, AnyComparisonCell] = {}
    for column in columns:
        value = io.get(column.key)
        if isinstance(value, ItemRef):
            item_cell = item_cells.get(value)
            if item_cell:
                cells[column.key] = item_cell.cell
                metadata_keys[column.key].update(item_cell.metadata_keys)
                continue
        elif isinstance(value, ItemRefs):
            members = [item_cells[ref] for ref in value.refs if ref in item_cells]
            if members:
                cells[column.key] = DatasetListCell(items=[member.cell for member in members])
                for member in members:
                    metadata_keys[column.key].update(member.metadata_keys)
                continue
        elif value is not None:
            cells[column.key] = value
            continue
        in_row_version = in_version is None or column.key in in_version
        cells[column.key] = MissingCell(reason=reason if in_row_version else "not_in_version")
    return cells


def _mark_skipped_outputs(io: dict[str, IoValue], job: JobRecord | None) -> None:
    """A skipped job's outputs are null placeholder datasets; show them as skipped."""
    if job and job.state == Job.states.SKIPPED:
        for key in io:
            if key.startswith("output:"):
                io[key] = MissingCell(reason="skipped")


def _set_metadata_keys(columns: list[ComparisonColumn], metadata_keys: dict[str, set[str]]) -> None:
    for column in columns:
        column.metadata_keys = sorted(metadata_keys[column.key])


def _history_ref(row: InvocationPageRow | ToolRunPageRow) -> HistoryRef:
    return HistoryRef(id=row.history_id, name=row.history_name, deleted=row.history_deleted, purged=row.history_purged)


def _item_refs(ios: Iterable[Mapping[str, IoValue]]) -> Iterator[ItemRef]:
    """Every dataset and collection the rows' io refers to, multiple input members included."""
    for io in ios:
        for value in io.values():
            if isinstance(value, ItemRef):
                yield value
            elif isinstance(value, ItemRefs):
                yield from value.refs


def _keyed(role: str, items: Mapping[str, IoValueT]) -> dict[str, IoValueT]:
    """Role-prefix normalized io names; an exact name wins over names folded into it."""
    keyed: dict[str, IoValueT] = {}
    for name, ref in items.items():
        normalized = normalize_io_name(name)
        key = f"{role}:{normalized}"
        if normalized == name:
            keyed[key] = ref
        else:
            keyed.setdefault(key, ref)
    return keyed


def _column_spec(key: str) -> ColumnSpec:
    """Column of a role-prefixed key from ``_keyed`` or ``_request_inputs``."""
    role, name = key.split(":", 1)
    column_role: ComparisonColumnRole = "parameter" if role == "parameter" else "input" if role == "input" else "output"
    return ColumnSpec(key=key, label=name, role=column_role)


def _step_state(
    step: InvocationStepRecord | None, job: JobRecord | None, icj: ImplicitCollectionJobsRecord | None
) -> str:
    if job:
        return job.state
    if icj:
        return (
            summary_state(icj.states)
            if icj.job_count
            else EMPTY_BATCH_STATES.get(icj.populated_state, JobState.NEW.value)
        )
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


def _review_action(step: InvocationStepRecord | None) -> bool | None:
    """A pause step's review decision; only pause steps take actions."""
    if step is None or step.action is None:
        return None
    return bool(step.action)


def _reused(job: JobRecord | None, icj: ImplicitCollectionJobsRecord | None) -> ReusedState | None:
    if job:
        return reused_state(int(job.copied), 1)
    if icj and icj.job_count:
        return reused_state(icj.copied_count, icj.job_count)
    return None
