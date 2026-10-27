"""Batch loading of the job, invocation step and io records comparison rows are built from."""

from collections import defaultdict
from collections.abc import (
    Callable,
    Collection,
    Iterable,
)
from typing import (
    Any,
    Literal,
    NamedTuple,
    TypeAlias,
)

from sqlalchemy import (
    or_,
    select,
)
from sqlalchemy.orm import InstrumentedAttribute

from galaxy.managers.comparison_columns import (
    ColumnSpec,
    multiple_input_members,
    normalize_io_name,
)
from galaxy.managers.comparison_queries import output_labels_stmt
from galaxy.managers.comparison_states import (
    EMPTY_BATCH_STATES,
    reused_state,
    summary_state,
)
from galaxy.model import (
    DatasetCollectionElement,
    HistoryDatasetCollectionAssociation,
    ImplicitCollectionJobs,
    ImplicitCollectionJobsJobAssociation,
    ImplicitlyCreatedDatasetCollectionInput,
    Job,
    JobToInputDatasetAssociation,
    JobToInputDatasetCollectionAssociation,
    JobToInputDatasetCollectionElementAssociation,
    JobToOutputDatasetAssociation,
    JobToOutputDatasetCollectionAssociation,
    Workflow,
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
    ComparisonColumnRole,
    ImplicitCollectionJobsRunRef,
    JobRunRef,
    MissingCell,
    ReusedState,
    ValueCell,
    WorkflowRunVia,
)
from galaxy.schema.states import JobState

INPUT_STEP_TYPES = ("data_input", "data_collection_input", "parameter_input")
JOB_RECORD_COLUMNS = (Job.id, Job.state, Job.tool_id, Job.tool_version, Job.copied_from_job_id.is_not(None))


class ItemRef(NamedTuple):
    src: Literal["hda", "hdca"]
    id: int


class ItemRefs(NamedTuple):
    """The datasets of a multiple data input, in order."""

    refs: tuple[ItemRef, ...]


IoValue: TypeAlias = ItemRef | ItemRefs | AnyComparisonCell
SubmissionKey: TypeAlias = tuple[Literal["job", "icj"], int]


class JobRecord(NamedTuple):
    id: int
    state: str
    tool_id: str | None
    tool_version: str | None
    copied: bool

    @property
    def key(self) -> SubmissionKey:
        return ("job", self.id)

    @property
    def reused(self) -> ReusedState:
        return reused_state(int(self.copied), 1)

    @property
    def outputs_skipped(self) -> bool:
        """A skipped job's outputs are null placeholder datasets."""
        return self.state == JobState.SKIPPED

    def run_ref(self) -> JobRunRef:
        return JobRunRef(id=self.id, state=self.state)


class ImplicitCollectionJobsRecord(NamedTuple):
    id: int
    populated_state: str
    representative: JobRecord | None
    states: dict[str, int]
    job_count: int
    copied_count: int

    @property
    def key(self) -> SubmissionKey:
        return ("icj", self.id)

    @property
    def state(self) -> str:
        if self.job_count:
            return summary_state(self.states)
        return EMPTY_BATCH_STATES.get(self.populated_state, JobState.NEW.value)

    @property
    def tool_id(self) -> str | None:
        return self.representative.tool_id if self.representative else None

    @property
    def tool_version(self) -> str | None:
        return self.representative.tool_version if self.representative else None

    @property
    def reused(self) -> ReusedState | None:
        return reused_state(self.copied_count, self.job_count) if self.job_count else None

    @property
    def outputs_skipped(self) -> bool:
        """A batch's outputs are collections, which show their own state."""
        return False

    def run_ref(self) -> ImplicitCollectionJobsRunRef:
        return ImplicitCollectionJobsRunRef(
            model="ImplicitCollectionJobs",
            id=self.id,
            populated_state=self.populated_state,
            representative_job_id=self.representative.id if self.representative else None,
            job_count=self.job_count,
            states=self.states,
        )


# One submission of a tool: a plain job, or a mapped batch shown by its first job.
Submission: TypeAlias = JobRecord | ImplicitCollectionJobsRecord


def submission_key(job_id: int | None, implicit_collection_jobs_id: int | None) -> SubmissionKey | None:
    """A mapped batch's key when there is one, else the plain job's."""
    if implicit_collection_jobs_id is not None:
        return ("icj", implicit_collection_jobs_id)
    return ("job", job_id) if job_id is not None else None


class LabelledStep(NamedTuple):
    """The step of one Workflow version that carries the compared label."""

    id: int
    type: str


class InvocationStepRecord(NamedTuple):
    id: int
    workflow_invocation_id: int
    state: str | None
    job_id: int | None
    implicit_collection_jobs_id: int | None
    action: Any


class IoSource(NamedTuple):
    """An association column holding io values, and how a row becomes a cell key and value."""

    role: ComparisonColumnRole
    value_column: InstrumentedAttribute[Any]
    to_value: Callable[[Any], IoValue]
    # parameters and output values are real values even when null
    keep_null: bool = False


def _hda_ref(hda_id: int) -> ItemRef:
    return ItemRef("hda", hda_id)


def _hdca_ref(hdca_id: int) -> ItemRef:
    return ItemRef("hdca", hdca_id)


def _parameter_cell(value: Any) -> ValueCell:
    return ValueCell(value=value, source="parameter")


def _output_value_cell(value: Any) -> ValueCell | MissingCell:
    """A workflow output value; a skipped step's ``NoReplacement`` sentinel renders as skipped."""
    if isinstance(value, dict) and value.get("__class__") == "NoReplacement":
        return MissingCell(reason="skipped")
    return ValueCell(value=value, source="output_value")


REQUEST_INPUT_SOURCES = (
    IoSource("input", WorkflowRequestToInputDatasetAssociation.dataset_id, _hda_ref),
    IoSource("input", WorkflowRequestToInputDatasetCollectionAssociation.dataset_collection_id, _hdca_ref),
    IoSource("parameter", WorkflowRequestInputStepParameter.parameter_value, _parameter_cell, keep_null=True),
)
INVOCATION_OUTPUT_SOURCES = (
    IoSource("output", WorkflowInvocationOutputDatasetAssociation.dataset_id, _hda_ref),
    IoSource("output", WorkflowInvocationOutputDatasetCollectionAssociation.dataset_collection_id, _hdca_ref),
    IoSource("output", WorkflowInvocationOutputValue.value, _output_value_cell, keep_null=True),
)
# a collection output wins its name over a dataset output
STEP_OUTPUT_COLUMNS: tuple[tuple[InstrumentedAttribute[Any], Literal["hda", "hdca"]], ...] = (
    (WorkflowInvocationStepOutputDatasetAssociation.dataset_id, "hda"),
    (WorkflowInvocationStepOutputDatasetCollectionAssociation.dataset_collection_id, "hdca"),
)


class ComparisonRecordLoader:
    """Loads, in a fixed number of statements per page, the records behind a page of comparison rows."""

    def __init__(self, sa_session: galaxy_scoped_session):
        self.sa_session = sa_session

    # Workflow definitions.

    def version_map(self, stored_workflow_id: int) -> dict[int, int]:
        """0-based version of each Workflow of a StoredWorkflow, as ``StoredWorkflow.version_of`` numbers them."""
        stmt = select(Workflow.id).where(Workflow.stored_workflow_id == stored_workflow_id).order_by(Workflow.id)
        return {workflow_id: version for version, workflow_id in enumerate(self.sa_session.scalars(stmt))}

    def labelled_steps(self, stored_workflow_id: int, label: str) -> dict[int, LabelledStep]:
        """The step labelled ``label`` in each Workflow version of a StoredWorkflow that has one."""
        stmt = (
            select(WorkflowStep.workflow_id, WorkflowStep.id, WorkflowStep.type)
            .join(Workflow, Workflow.id == WorkflowStep.workflow_id)
            .where(Workflow.stored_workflow_id == stored_workflow_id, WorkflowStep.label == label)
        )
        return {
            workflow_id: LabelledStep(step_id, step_type)
            for workflow_id, step_id, step_type in self.sa_session.execute(stmt)
        }

    def declared_workflow_io(self, workflow_ids: Collection[int]) -> dict[int, list[ColumnSpec]]:
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
        for workflow_id, label in self.sa_session.execute(output_labels_stmt(workflow_ids)):
            declared[workflow_id].append(ColumnSpec(key=f"output:{label}", label=label, role="output"))
        return declared

    def defined_step_inputs(self, step_ids: Collection[int]) -> dict[int, set[str]]:
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

    # Invocations.

    def invocation_io(self, invocation_ids: list[int]) -> dict[int, dict[str, IoValue]]:
        """Labelled inputs, parameters and outputs of each invocation; the first output by id wins a label."""
        io = self.request_inputs(invocation_ids)
        if not invocation_ids:
            return io
        outputs: dict[tuple[int, str], tuple[int, IoValue]] = {}
        for source in INVOCATION_OUTPUT_SOURCES:
            assoc = source.value_column.class_
            stmt = (
                select(assoc.workflow_invocation_id, WorkflowOutput.id, WorkflowOutput.label, source.value_column)
                .join(WorkflowOutput, WorkflowOutput.id == assoc.workflow_output_id)
                .where(assoc.workflow_invocation_id.in_(invocation_ids), WorkflowOutput.label.is_not(None))
            )
            if not source.keep_null:
                stmt = stmt.where(source.value_column.is_not(None))
            for invocation_id, output_id, label, value in self.sa_session.execute(stmt):
                output_key = (invocation_id, f"{source.role}:{label}")
                if output_key not in outputs or output_id < outputs[output_key][0]:
                    outputs[output_key] = (output_id, source.to_value(value))
        for (invocation_id, column_key), (_, output_value) in outputs.items():
            io[invocation_id][column_key] = output_value
        return io

    def request_inputs(
        self, invocation_ids: list[int], step_ids: Collection[int] | None = None
    ) -> dict[int, dict[str, IoValue]]:
        """Labelled input steps' datasets, collections and values each invocation was requested with."""
        inputs: dict[int, dict[str, IoValue]] = defaultdict(dict)
        if not invocation_ids:
            return inputs
        for source in REQUEST_INPUT_SOURCES:
            assoc = source.value_column.class_
            stmt = (
                select(assoc.workflow_invocation_id, WorkflowStep.label, source.value_column)
                .join(WorkflowStep, WorkflowStep.id == assoc.workflow_step_id)
                .where(assoc.workflow_invocation_id.in_(invocation_ids), WorkflowStep.label.is_not(None))
                .order_by(assoc.id)
            )
            if not source.keep_null:
                stmt = stmt.where(source.value_column.is_not(None))
            if step_ids is not None:
                stmt = stmt.where(assoc.workflow_step_id.in_(step_ids))
            for invocation_id, label, value in self.sa_session.execute(stmt):
                inputs[invocation_id].setdefault(f"{source.role}:{label}", source.to_value(value))
        return inputs

    def invocation_steps(self, invocation_ids: list[int], step_ids: list[int]) -> dict[int, InvocationStepRecord]:
        """The first invocation step of ``step_ids`` in each invocation."""
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

    def step_outputs(self, invocation_step_ids: list[int]) -> dict[int, dict[str, ItemRef]]:
        """Output datasets and collections of each invocation step, keyed by output name."""
        outputs: dict[int, dict[str, ItemRef]] = defaultdict(dict)
        if not invocation_step_ids:
            return outputs
        for value_column, src in STEP_OUTPUT_COLUMNS:
            assoc = value_column.class_
            stmt = (
                select(assoc.workflow_invocation_step_id, assoc.output_name, value_column)
                .where(assoc.workflow_invocation_step_id.in_(invocation_step_ids), value_column.is_not(None))
                .order_by(assoc.id)
            )
            for step_id, name, item_id in self.sa_session.execute(stmt):
                outputs[step_id][name] = ItemRef(src, item_id)
        return outputs

    def subworkflow_invocations(self, invocation_ids: list[int], step_ids: list[int]) -> dict[int, int]:
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

    # Submissions: plain jobs and mapped batches.

    def submissions(self, keys: Iterable[SubmissionKey]) -> dict[SubmissionKey, Submission]:
        job_ids, icj_ids = _split_keys(keys)
        jobs = self._jobs(job_ids)
        icjs = self._implicit_collection_jobs(icj_ids)
        records: list[Submission] = [*jobs.values(), *icjs.values()]
        return {record.key: record for record in records}

    def submission_inputs(
        self, submissions: Collection[Submission]
    ) -> dict[SubmissionKey, dict[str, ItemRef | ItemRefs]]:
        """Inputs of each submission; a batch has its first job's inputs plus the mapped-over ones."""
        job_ids, icjs = _split_submissions(submissions)
        representatives = {icj.id: icj.representative.id for icj in icjs if icj.representative}
        job_inputs = self._job_inputs([*job_ids, *representatives.values()])
        mapped_inputs = self._implicit_collection_inputs([icj.id for icj in icjs])
        inputs: dict[SubmissionKey, dict[str, ItemRef | ItemRefs]] = {
            ("job", job_id): job_inputs.get(job_id, {}) for job_id in job_ids
        }
        for icj in icjs:
            first_job = job_inputs.get(representatives[icj.id], {}) if icj.id in representatives else {}
            inputs[icj.key] = {**first_job, **mapped_inputs.get(icj.id, {})}
        return inputs

    def submission_outputs(self, submissions: Collection[Submission]) -> dict[SubmissionKey, dict[str, ItemRef]]:
        """Output datasets of each plain job and collections of each batch, keyed by output name."""
        job_ids, icjs = _split_submissions(submissions)
        job_outputs = self._job_outputs(job_ids)
        icj_outputs = self._implicit_collection_outputs([icj.id for icj in icjs])
        outputs: dict[SubmissionKey, dict[str, ItemRef]] = {
            ("job", job_id): named for job_id, named in job_outputs.items()
        }
        outputs.update((("icj", icj_id), named) for icj_id, named in icj_outputs.items())
        return outputs

    def workflow_runs_via(self, submissions: Collection[Submission]) -> dict[SubmissionKey, WorkflowRunVia]:
        """The invocation step that ran each submission."""
        job_ids, icjs = _split_submissions(submissions)
        icj_ids = [icj.id for icj in icjs]
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
        via: dict[SubmissionKey, WorkflowRunVia] = {}
        for job_id, icj_id, invocation_id, step_label, workflow_name in self.sa_session.execute(stmt):
            key = submission_key(job_id, icj_id)
            assert key is not None
            via[key] = WorkflowRunVia(invocation_id=invocation_id, step_label=step_label, workflow_name=workflow_name)
        return via

    def _jobs(self, job_ids: Collection[int]) -> dict[int, JobRecord]:
        if not job_ids:
            return {}
        stmt = select(*JOB_RECORD_COLUMNS).where(Job.id.in_(job_ids))
        return {row[0]: JobRecord(*row) for row in self.sa_session.execute(stmt)}

    def _implicit_collection_jobs(self, icj_ids: Collection[int]) -> dict[int, ImplicitCollectionJobsRecord]:
        """Member job states, reuse and the representative (first) job of each mapped batch."""
        if not icj_ids:
            return {}
        icj = ImplicitCollectionJobs
        icjja = ImplicitCollectionJobsJobAssociation
        # outer joins keep batches mapped over an empty collection
        stmt = (
            select(icj.id, icj.populated_state, *JOB_RECORD_COLUMNS)
            .outerjoin(icjja, icjja.implicit_collection_jobs_id == icj.id)
            .outerjoin(Job, Job.id == icjja.job_id)
            .where(icj.id.in_(icj_ids))
            .order_by(icj.id, icjja.order_index, icjja.job_id)
        )
        populated_states: dict[int, str] = {}
        members: dict[int, list[JobRecord]] = defaultdict(list)
        for icj_id, populated_state, *job_columns in self.sa_session.execute(stmt):
            populated_states[icj_id] = populated_state
            if job_columns[0] is not None:
                members[icj_id].append(JobRecord(*job_columns))
        records = {}
        for icj_id, populated_state in populated_states.items():
            jobs = members[icj_id]
            states: dict[str, int] = defaultdict(int)
            for member in jobs:
                states[member.state] += 1
            records[icj_id] = ImplicitCollectionJobsRecord(
                id=icj_id,
                populated_state=populated_state,
                representative=jobs[0] if jobs else None,
                states=dict(states),
                job_count=len(jobs),
                copied_count=sum(job.copied for job in jobs),
            )
        return records

    def _job_inputs(self, job_ids: Collection[int]) -> dict[int, dict[str, ItemRef | ItemRefs]]:
        """Input datasets and collections of each job, keyed by association name."""
        inputs: dict[int, dict[str, ItemRef | ItemRefs]] = defaultdict(dict)
        if not job_ids:
            return inputs
        jtida = JobToInputDatasetAssociation
        dataset_ids: dict[int, dict[str, int]] = defaultdict(dict)
        stmt = (
            select(jtida.job_id, jtida.name, jtida.dataset_id)
            .where(jtida.job_id.in_(job_ids), jtida.dataset_id.is_not(None))
            .order_by(jtida.id)
        )
        for job_id, name, dataset_id in self.sa_session.execute(stmt):
            dataset_ids[job_id][name] = dataset_id
        for job_id, by_name in dataset_ids.items():
            members = multiple_input_members(by_name)
            folded = {name for names in members.values() for name in names}
            for name, dataset_id in by_name.items():
                if name in folded:
                    continue
                names = members.get(name, ())
                if len(names) > 1:
                    inputs[job_id][name] = ItemRefs(tuple(ItemRef("hda", by_name[member]) for member in names))
                else:
                    inputs[job_id][name] = ItemRef("hda", dataset_id)

        jtidca = JobToInputDatasetCollectionAssociation
        collection_stmt = (
            select(jtidca.job_id, jtidca.name, jtidca.dataset_collection_id)
            .where(jtidca.job_id.in_(job_ids), jtidca.dataset_collection_id.is_not(None))
            .order_by(jtidca.id)
        )
        for job_id, name, hdca_id in self.sa_session.execute(collection_stmt):
            inputs[job_id][name] = ItemRef("hdca", hdca_id)

        jtidcea = JobToInputDatasetCollectionElementAssociation
        element_stmt = (
            select(jtidcea.job_id, jtidcea.name, DatasetCollectionElement.hda_id)
            .join(DatasetCollectionElement, DatasetCollectionElement.id == jtidcea.dataset_collection_element_id)
            .where(jtidcea.job_id.in_(job_ids), DatasetCollectionElement.hda_id.is_not(None))
            .order_by(jtidcea.id)
        )
        for job_id, name, hda_id in self.sa_session.execute(element_stmt):
            inputs[job_id].setdefault(name, ItemRef("hda", hda_id))
        return inputs

    def _implicit_collection_inputs(self, icj_ids: Collection[int]) -> dict[int, dict[str, ItemRef]]:
        """Collections a mapped batch was mapped over, keyed by input name."""
        inputs: dict[int, dict[str, ItemRef]] = defaultdict(dict)
        if not icj_ids:
            return inputs
        hdca = HistoryDatasetCollectionAssociation
        icdci = ImplicitlyCreatedDatasetCollectionInput
        stmt = (
            select(hdca.implicit_collection_jobs_id, icdci.name, icdci.input_dataset_collection_id)
            .join(icdci, icdci.dataset_collection_id == hdca.id)
            .where(hdca.implicit_collection_jobs_id.in_(icj_ids), icdci.input_dataset_collection_id.is_not(None))
            .order_by(icdci.id)
        )
        for icj_id, name, input_hdca_id in self.sa_session.execute(stmt):
            inputs[icj_id].setdefault(name, ItemRef("hdca", input_hdca_id))
        return inputs

    def _job_outputs(self, job_ids: Collection[int]) -> dict[int, dict[str, ItemRef]]:
        """Output datasets and collections of each job, keyed by association name."""
        outputs: dict[int, dict[str, ItemRef]] = defaultdict(dict)
        if not job_ids:
            return outputs
        jtoda = JobToOutputDatasetAssociation
        stmt = (
            select(jtoda.job_id, jtoda.name, jtoda.dataset_id)
            .where(jtoda.job_id.in_(job_ids), jtoda.dataset_id.is_not(None))
            .order_by(jtoda.id)
        )
        for job_id, name, hda_id in self.sa_session.execute(stmt):
            outputs[job_id].setdefault(name, ItemRef("hda", hda_id))
        jtodca = JobToOutputDatasetCollectionAssociation
        collection_stmt = (
            select(jtodca.job_id, jtodca.name, jtodca.dataset_collection_id)
            .where(jtodca.job_id.in_(job_ids), jtodca.dataset_collection_id.is_not(None))
            .order_by(jtodca.id)
        )
        for job_id, name, hdca_id in self.sa_session.execute(collection_stmt):
            outputs[job_id][name] = ItemRef("hdca", hdca_id)
        return outputs

    def _implicit_collection_outputs(self, icj_ids: Collection[int]) -> dict[int, dict[str, ItemRef]]:
        """Collections a mapped batch created, keyed by output name."""
        outputs: dict[int, dict[str, ItemRef]] = defaultdict(dict)
        if not icj_ids:
            return outputs
        hdca = HistoryDatasetCollectionAssociation
        stmt = (
            select(hdca.implicit_collection_jobs_id, hdca.implicit_output_name, hdca.id)
            .where(hdca.implicit_collection_jobs_id.in_(icj_ids), hdca.implicit_output_name.is_not(None))
            .order_by(hdca.id)
        )
        for icj_id, name, hdca_id in self.sa_session.execute(stmt):
            outputs[icj_id].setdefault(name, ItemRef("hdca", hdca_id))
        return outputs


def _split_keys(keys: Iterable[SubmissionKey]) -> tuple[set[int], set[int]]:
    job_ids: set[int] = set()
    icj_ids: set[int] = set()
    for kind, submission_id in keys:
        (icj_ids if kind == "icj" else job_ids).add(submission_id)
    return job_ids, icj_ids


def _split_submissions(submissions: Iterable[Submission]) -> tuple[list[int], list[ImplicitCollectionJobsRecord]]:
    job_ids: list[int] = []
    icjs: list[ImplicitCollectionJobsRecord] = []
    for submission in submissions:
        if isinstance(submission, ImplicitCollectionJobsRecord):
            icjs.append(submission)
        else:
            job_ids.append(submission.id)
    return job_ids, icjs
