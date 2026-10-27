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
    RowIo,
)
from galaxy.managers.comparison_columns import (
    align_columns,
    ColumnSpec,
    keyed_io,
)
from galaxy.managers.comparison_queries import (
    invoked_workflows_stmt,
    output_labels_stmt,
    selected_versions,
    step_state_predicate,
    submission_state_predicate,
    tool_predicates,
)
from galaxy.managers.comparison_records import (
    ComparisonRecordLoader,
    INPUT_STEP_TYPES,
    InvocationStepRecord,
    IoValue,
    Submission,
    submission_key,
    SubmissionKey,
)
from galaxy.managers.comparison_states import missing_reason
from galaxy.managers.workflows import get_count
from galaxy.model import (
    History,
    ImplicitCollectionJobsJobAssociation,
    Job,
    Workflow,
    WorkflowInvocation,
    WorkflowInvocationStep,
    WorkflowStep,
)
from galaxy.model.scoped_session import galaxy_scoped_session
from galaxy.schema.comparisons import (
    ComparisonColumn,
    ComparisonQueryBase,
    ComparisonRow,
    ComparisonTable,
    HistoryRef,
    InvocationRunRef,
    MissingCell,
    OutputRunsQuery,
    StepRunsQuery,
    ToolRunsQuery,
)
from galaxy.schema.states import InvocationState
from galaxy.tool_util.version import parse_tool_version

NOT_SCHEDULED_INVOCATION_STATES = (
    InvocationState.NEW,
    InvocationState.READY,
    InvocationState.REQUIRES_MATERIALIZATION,
)


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

    @property
    def submission_key(self) -> SubmissionKey:
        if self.implicit_collection_jobs_id is not None:
            return ("icj", self.implicit_collection_jobs_id)
        return ("job", self.job_id)


class ComparisonsManager:
    def __init__(
        self, sa_session: galaxy_scoped_session, records: ComparisonRecordLoader, cell_builder: ComparisonCellBuilder
    ):
        self.sa_session = sa_session
        self.records = records
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
        state_predicate = step_state_predicate(step_ids, query.states) if query.states else None
        version_map = self.records.version_map(stored_workflow_id)
        workflow_ids = selected_versions({wid: version_map[wid] for wid in steps_by_workflow}, query.versions)
        page, total = self._page_invocations(access.user_id, workflow_ids, query, state_predicate)
        step_by_workflow = {workflow_id: step_id for workflow_id, (step_id, _) in steps_by_workflow.items()}
        columns, rows = self._step_rows(access, page, step_by_workflow, step_types, query, version_map)
        invoked = self.sa_session.scalars(invoked_workflows_stmt(access.user_id, steps_by_workflow).distinct())
        versions_available = sorted(version_map[workflow_id] for workflow_id in invoked)
        table = ComparisonTable(query=query, columns=columns, rows=rows, versions_available=versions_available)
        return table, total

    def output_runs(
        self, access: ComparisonAccess, stored_workflow_id: int, query: OutputRunsQuery
    ) -> tuple[ComparisonTable, int]:
        """One row per invocation of any version, with labelled workflow inputs and outputs as columns."""
        version_map = self.records.version_map(stored_workflow_id)
        state_predicate = WorkflowInvocation.state.in_(query.states) if query.states else None
        workflow_ids = selected_versions(version_map, query.versions)
        page, total = self._page_invocations(access.user_id, workflow_ids, query, state_predicate)
        columns, rows = self._output_rows(access, page, query, version_map)
        output_labels = self._invoked_output_labels(access.user_id, version_map)
        invoked = self.sa_session.scalars(invoked_workflows_stmt(access.user_id, version_map).distinct())
        table = ComparisonTable(
            query=query,
            columns=columns,
            rows=rows,
            output_labels_available=output_labels,
            versions_available=sorted(version_map[workflow_id] for workflow_id in invoked),
        )
        return table, total

    def tool_runs(self, access: ComparisonAccess, query: ToolRunsQuery) -> tuple[ComparisonTable, int]:
        """One row per submission of a tool: a plain job, or a mapped batch shown by its first job."""
        predicates = tool_predicates(access.user_id, query.tool_id)
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
        page_rows, total = self._count_and_page(stmt, Job.id, Job.update_time, query)
        page = [ToolRunPageRow(*row) for row in page_rows]
        columns, rows = self._tool_rows(access, page, query)
        table = ComparisonTable(
            query=query, columns=columns, rows=rows, tool_versions_available=self._tool_versions(predicates)
        )
        return table, total

    def _invoked_output_labels(self, user_id: int, version_map: dict[int, int]) -> list[str]:
        """Output labels of every version the user has invoked, newest version first, then step order."""
        labels: dict[int, list[str]] = defaultdict(list)
        invoked = invoked_workflows_stmt(user_id, version_map)
        for workflow_id, label in self.sa_session.execute(output_labels_stmt(invoked)):
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
        declared = self.records.declared_workflow_io({invocation.workflow_id for invocation in page})
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
        io_by_invocation = self.records.invocation_io([invocation.id for invocation in page])
        rows: list[ComparisonRow] = []
        row_ios: list[RowIo] = []
        for invocation in page:
            version = version_map[invocation.workflow_id]
            state = invocation.state or InvocationState.NEW.value
            scheduled = state not in NOT_SCHEDULED_INVOCATION_STATES
            io = {key: value for key, value in io_by_invocation.get(invocation.id, {}).items() if key in column_keys}
            in_version = {spec.key for spec in declared_by_version.get(version, ())}
            row_ios.append(RowIo(io, in_version, missing_reason(state if scheduled else None, None, True)))
            rows.append(
                ComparisonRow(
                    run=InvocationRunRef(id=invocation.id, state=state),
                    create_time=invocation.create_time,
                    update_time=invocation.update_time,
                    state=state,
                    version=version,
                    history=_history_ref(invocation),
                    cells={},
                )
            )
        self._fill_cells(rows, columns, row_ios, access, query)
        return columns, rows

    def _tool_rows(
        self, access: ComparisonAccess, page: list[ToolRunPageRow], query: ToolRunsQuery
    ) -> tuple[list[ComparisonColumn], list[ComparisonRow]]:
        submissions = self.records.submissions(row.submission_key for row in page)
        inputs = self.records.submission_inputs(submissions.values())
        outputs = self.records.submission_outputs(submissions.values())
        via = self.records.workflow_runs_via(submissions.values())

        # the loaders return every paged id, so total_matches and rows agree
        paged = [submissions[row.submission_key] for row in page]
        ios: list[dict[str, IoValue]] = []
        specs: dict[str, ColumnSpec] = {}
        declared: dict[str | None, set[str]] = defaultdict(set)
        for submission in paged:
            io: dict[str, IoValue] = {
                **keyed_io("input", inputs.get(submission.key, {})),
                **keyed_io("output", outputs.get(submission.key, {})),
            }
            _mark_skipped_outputs(io, submission)
            ios.append(io)
            declared[submission.tool_version].update(io)
            for key in io:
                specs.setdefault(key, ColumnSpec.of_key(key))
        columns = align_columns({0: list(specs.values())}, 0)

        rows: list[ComparisonRow] = []
        row_ios: list[RowIo] = []
        for row, submission, io in zip(page, paged, ios):
            state = submission.state
            # a tool version's columns are only known from its rows on this page
            reason = missing_reason(state, state, state not in Job.non_ready_states)
            row_ios.append(RowIo(io, declared[submission.tool_version], reason))
            rows.append(
                ComparisonRow(
                    run=submission.run_ref(),
                    via=via.get(submission.key),
                    create_time=row.create_time,
                    update_time=row.update_time,
                    state=state,
                    tool_id=submission.tool_id,
                    tool_version=submission.tool_version,
                    reused=submission.reused,
                    history=_history_ref(row),
                    cells={},
                )
            )
        self._fill_cells(rows, columns, row_ios, access, query)
        return columns, rows

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
        steps = self.records.invocation_steps(invocation_ids, step_ids)
        outputs = self.records.step_outputs([step.id for step in steps.values()])
        step_submissions = {
            invocation_id: submission_key(step.job_id, step.implicit_collection_jobs_id)
            for invocation_id, step in steps.items()
        }
        submissions = self.records.submissions(key for key in step_submissions.values() if key)
        inputs = self.records.submission_inputs(submissions.values())
        subworkflow_invocations = self.records.subworkflow_invocations(invocation_ids, step_ids)
        request_inputs = self.records.request_inputs(invocation_ids, step_ids)

        rows: list[ComparisonRow] = []
        ios: list[dict[str, IoValue]] = []
        declared: dict[int, dict[str, ColumnSpec]] = defaultdict(dict)
        for invocation in page:
            version = version_map[invocation.workflow_id]
            step_type = step_types[invocation.workflow_id]
            step = steps.get(invocation.id)
            key = step_submissions.get(invocation.id)
            submission = submissions.get(key) if key else None
            # an input step's own input; its step output is the same item
            io: dict[str, IoValue] = dict(request_inputs.get(invocation.id, {}))
            if step and step_type not in INPUT_STEP_TYPES:
                io.update(keyed_io("input", inputs.get(submission.key, {}) if submission else {}))
                io.update(keyed_io("output", outputs.get(step.id, {})))
                _mark_skipped_outputs(io, submission)
            ios.append(io)
            for column_key in io:
                declared[version].setdefault(column_key, ColumnSpec.of_key(column_key))
            rows.append(
                ComparisonRow(
                    run=InvocationRunRef(id=invocation.id, state=invocation.state or "new"),
                    step_job=submission.run_ref() if submission else None,
                    subworkflow_invocation_id=subworkflow_invocations.get(invocation.id),
                    step_type=step_type,
                    step_action=_review_action(step),
                    create_time=invocation.create_time,
                    update_time=invocation.update_time,
                    state=_step_state(step, submission),
                    version=version,
                    tool_id=submission.tool_id if submission else None,
                    tool_version=submission.tool_version if submission else None,
                    reused=submission.reused if submission else None,
                    history=_history_ref(invocation),
                    cells={},
                )
            )
        self._declare_defined_step_io(declared, page, step_by_workflow, version_map)
        newest_version = max(declared) if declared else 0
        columns = align_columns({v: list(specs.values()) for v, specs in declared.items()}, newest_version)

        row_ios: list[RowIo] = []
        for invocation, row, io in zip(page, rows, ios):
            step = steps.get(invocation.id)
            terminal = row.state not in Job.non_ready_states
            reason = missing_reason((step.state or "new") if step else None, row.state, terminal)
            # an input step's one column is in every version with the step
            is_input_step = step_types[invocation.workflow_id] in INPUT_STEP_TYPES
            row_ios.append(RowIo(io, None if is_input_step else declared[version_map[invocation.workflow_id]], reason))
        self._fill_cells(rows, columns, row_ios, access, query)
        return columns, rows

    def _declare_defined_step_io(
        self,
        declared: dict[int, dict[str, ColumnSpec]],
        page: list[InvocationPageRow],
        step_by_workflow: dict[int, int],
        version_map: dict[int, int],
    ) -> None:
        """Declare, for each version, the page's columns its step definition has though its runs left them empty."""
        observed = list(dict.fromkeys(key for specs in declared.values() for key in specs))
        page_workflow_ids = {invocation.workflow_id for invocation in page}
        defined = self.records.defined_step_inputs([step_by_workflow[workflow_id] for workflow_id in page_workflow_ids])
        for workflow_id in page_workflow_ids:
            version_specs = declared[version_map[workflow_id]]
            step_defines = defined.get(step_by_workflow[workflow_id], set())
            # a version none of whose runs here recorded outputs yet may have any of them
            outputs_unknown = not any(key.startswith("output:") for key in version_specs)
            for key in observed:
                if key in step_defines or (outputs_unknown and key.startswith("output:")):
                    version_specs.setdefault(key, ColumnSpec.of_key(key))

    def _fill_cells(
        self,
        rows: list[ComparisonRow],
        columns: list[ComparisonColumn],
        row_ios: list[RowIo],
        access: ComparisonAccess,
        query: ComparisonQueryBase,
    ) -> None:
        for row, cells in zip(rows, self.cell_builder.row_cells(columns, row_ios, access, query)):
            row.cells = cells

    def _tool_versions(self, predicates: list[ColumnElement[bool]]) -> list[str]:
        stmt = select(Job.tool_version).where(*predicates, Job.tool_version.is_not(None)).distinct()
        return sorted(self.sa_session.scalars(stmt), key=parse_tool_version)

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


def _mark_skipped_outputs(io: dict[str, IoValue], submission: Submission | None) -> None:
    """Show a skipped job's null placeholder outputs as skipped."""
    if submission and submission.outputs_skipped:
        for key in io:
            if key.startswith("output:"):
                io[key] = MissingCell(reason="skipped")


def _history_ref(row: InvocationPageRow | ToolRunPageRow) -> HistoryRef:
    return HistoryRef(id=row.history_id, name=row.history_name, deleted=row.history_deleted, purged=row.history_purged)


def _step_state(step: InvocationStepRecord | None, submission: Submission | None) -> str:
    if submission:
        return submission.state
    if step and step.state:
        return step.state
    return "new"


def _review_action(step: InvocationStepRecord | None) -> bool | None:
    """A pause step's review decision; only pause steps take actions."""
    if step is None or step.action is None:
        return None
    return bool(step.action)
