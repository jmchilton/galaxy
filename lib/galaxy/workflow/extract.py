"""This module contains functionality to aid in extracting workflows from
histories.
"""

import json
import logging
from collections.abc import Callable
from dataclasses import (
    dataclass,
    field,
)
from typing import (
    Any,
    cast,
    Literal,
    Optional,
)

from galaxy import (
    exceptions,
    model,
)
from galaxy.managers.context import ProvidesHistoryContext
from galaxy.managers.jobs import JobManager
from galaxy.model import (
    History,
    HistoryDatasetAssociation,
    HistoryDatasetCollectionAssociation,
    HistoryItem,
    ImplicitCollectionJobs,
    Job,
    StoredWorkflow,
    ToolRequest,
    User,
    WorkflowStep,
)
from galaxy.model.base import ensure_object_added_to_session
from galaxy.tool_util.parameters import (
    RequestInternalToolState,
    RequestInternalToWorkflowStateError,
    to_workflow_step_state,
    ToolParameterBundleModel,
)
from galaxy.tool_util.parameters.request import (
    request_internal_input_refs,
    request_internal_url_inputs,
    RequestInputRef,
    RequestUrlInputRef,
)
from galaxy.tool_util.parser import ToolOutputCollectionPart
from galaxy.tools import create_tool_from_representation
from galaxy.tools.parameters.basic import (
    DataCollectionToolParameter,
    DataToolParameter,
)
from galaxy.tools.parameters.grouping import (
    Conditional,
    Repeat,
    Section,
)
from galaxy.util import listify
from .steps import (
    attach_ordered_steps,
    order_workflow_steps_with_levels,
)

# Type alias for tool input parameter values (param name -> string value)
ToolInputs = dict[str, Any]

# Type alias for data input associations (hid, input_name) pairs linking
# history items to their corresponding tool input parameters
DataInputAssociations = list[tuple[int, str]]

log = logging.getLogger(__name__)

WARNING_SOME_DATASETS_NOT_READY = "Some datasets still queued or running were ignored"


def _skip_output_assoc_name(name: str) -> bool:
    """True for job-output-association names that aren't workflow-visible
    outputs (named-collection-part placeholders and discovered-primary-file
    rows). Both extraction paths skip these."""
    return ToolOutputCollectionPart.is_named_collection_part_name(name) or name.startswith("__new_primary_file")


def _connect(step: WorkflowStep, input_name: str, source: tuple[WorkflowStep, str]) -> None:
    """Wire ``step``'s ``input_name`` to ``source`` (output_step, output_name).
    The source is always an earlier step - a job only consumes outputs of jobs
    that ran before it. Shared by both extraction paths."""
    source_step, source_name = source
    conn = model.WorkflowStepConnection()
    conn.input_step_input = step.get_or_add_input(input_name)
    conn.output_step = source_step
    conn.output_name = source_name


def extract_workflow(
    trans: ProvidesHistoryContext,
    user: User,
    history: Optional[History] = None,
    job_ids: Optional[list[int]] = None,
    dataset_ids: Optional[list[int]] = None,
    dataset_collection_ids: Optional[list[int]] = None,
    workflow_name: Optional[str] = None,
    dataset_names: Optional[list[str]] = None,
    dataset_collection_names: Optional[list[str]] = None,
) -> StoredWorkflow:
    steps = extract_steps(
        trans,
        history=history,
        job_ids=job_ids,
        dataset_ids=dataset_ids,
        dataset_collection_ids=dataset_collection_ids,
        dataset_names=dataset_names,
        dataset_collection_names=dataset_collection_names,
    )
    return _finalize_workflow(trans, user, workflow_name, steps)


def _finalize_workflow(
    trans: ProvidesHistoryContext,
    user: User,
    workflow_name: Optional[str],
    steps: list[WorkflowStep],
) -> StoredWorkflow:
    workflow = model.Workflow()
    workflow.name = workflow_name
    workflow.steps = steps
    attach_ordered_steps(workflow)
    levorder = order_workflow_steps_with_levels(steps)
    base_pos = 10
    for i, steps_at_level in enumerate(levorder):
        for j, index in enumerate(steps_at_level):
            step = steps[index]
            step.position = dict(top=(base_pos + 120 * j), left=(base_pos + 220 * i))
    stored = model.StoredWorkflow()
    stored.user = user
    stored.name = workflow_name
    workflow.stored_workflow = stored
    stored.latest_workflow = workflow
    trans.sa_session.add(stored)
    ensure_object_added_to_session(workflow, session=trans.sa_session)
    trans.sa_session.commit()
    return stored


def extract_steps(
    trans: ProvidesHistoryContext,
    history: Optional[History] = None,
    job_ids: Optional[list[int]] = None,
    dataset_ids: Optional[list[int]] = None,
    dataset_collection_ids: Optional[list[int]] = None,
    dataset_names: Optional[list[str]] = None,
    dataset_collection_names: Optional[list[str]] = None,
) -> list[WorkflowStep]:
    # Ensure job_ids and dataset_ids are lists (possibly empty)
    job_ids = listify(job_ids)
    dataset_ids = listify(dataset_ids)
    dataset_collection_ids = listify(dataset_collection_ids)
    # Convert both sets of ids to integers
    job_ids = [int(_) for _ in job_ids]
    dataset_ids = [int(_) for _ in dataset_ids]
    dataset_collection_ids = [int(_) for _ in dataset_collection_ids]
    # Find each job, for security we (implicitly) check that they are
    # associated with a job in the current history.
    summary = WorkflowSummary(trans, history)
    jobs = summary.jobs
    steps = []
    step_labels = set()
    hid_to_output_pair = {}
    # Input dataset steps
    for i, input_hid in enumerate(dataset_ids):
        step = model.WorkflowStep()
        step.type = "data_input"
        if dataset_names:
            name = dataset_names[i]
        else:
            name = "Input Dataset"
        if name not in step_labels:
            step.label = name
            step_labels.add(name)
        step.tool_inputs = dict(name=name)
        hid_to_output_pair[input_hid] = (step, "output")
        steps.append(step)
    for i, input_hid in enumerate(dataset_collection_ids):
        step = model.WorkflowStep()
        step.type = "data_collection_input"
        if input_hid not in summary.collection_types:
            raise exceptions.RequestParameterInvalidException(f"hid {input_hid} does not appear to be a collection")
        collection_type = summary.collection_types[input_hid]
        if dataset_collection_names:
            name = dataset_collection_names[i]
        else:
            name = "Input Dataset Collection"
        if name not in step_labels:
            step.label = name
            step_labels.add(name)
        step.tool_inputs = dict(name=name, collection_type=collection_type)
        hid_to_output_pair[input_hid] = (step, "output")
        steps.append(step)
    # Tool steps
    for job_id in job_ids:
        if job_id not in summary.job_id2representative_job:
            log.warning(f"job_id {job_id} not found in job_id2representative_job {summary.job_id2representative_job}")
            raise AssertionError("Attempt to create workflow with job not connected to current history")
        job = summary.job_id2representative_job[job_id]
        tool_inputs, associations = step_inputs(trans, job)
        step = model.WorkflowStep()
        step.type = "tool"
        step.tool_id = job.tool_id
        step.tool_version = job.tool_version
        step.tool_inputs = tool_inputs
        # NOTE: We shouldn't need to do two passes here since only
        #       an earlier job can be used as an input to a later
        #       job.
        for other_hid, input_name in associations:
            if job in summary.implicit_map_jobs:
                an_implicit_output_collection = cast(HistoryDatasetCollectionAssociation, jobs[job][0][1])
                input_collection = an_implicit_output_collection.find_implicit_input_collection(input_name)
                if input_collection:
                    other_hid = input_collection.hid
                else:
                    log.info(f"Cannot find implicit input collection for {input_name}")
            if other_hid in hid_to_output_pair:
                _connect(step, input_name, hid_to_output_pair[other_hid])
        steps.append(step)
        # Store created dataset hids
        for assoc in job.output_datasets + job.output_dataset_collection_instances:
            assoc_name = assoc.name
            if _skip_output_assoc_name(assoc_name):
                continue
            if job in summary.implicit_map_jobs:
                hid: Optional[int] = None
                for implicit_pair in jobs[job]:
                    query_assoc_name, dataset_collection = implicit_pair
                    if query_assoc_name == assoc_name or assoc_name.startswith(
                        f"__new_primary_file_{query_assoc_name}|"
                    ):
                        hid = summary.hid(dataset_collection)
                if hid is None:
                    template = (
                        "Failed to find matching implicit job - job id is %s, implicit pairs are %s, assoc_name is %s."
                    )
                    message = template % (job.id, jobs[job], assoc_name)
                    log.warning(message)
                    raise Exception("Failed to extract job.")
            else:
                if hasattr(assoc, "dataset"):
                    has_hid = assoc.dataset
                else:
                    has_hid = assoc.dataset_collection_instance
                hid = summary.hid(has_hid)
            if hid in hid_to_output_pair:
                log.warning(f"duplicate hid found in extract_steps [{hid}]")
            hid_to_output_pair[hid] = (step, assoc.name)
    return steps


class FakeJob:
    """
    Fake job object for datasets that have no creating_job_associations,
    they will be treated as "input" datasets.
    """

    def __init__(self, dataset: HistoryDatasetAssociation) -> None:
        self.is_fake = True
        self.id = f"fake_{dataset.id}"
        self.name = self._guess_name_from_dataset(dataset)

    def _guess_name_from_dataset(self, dataset: HistoryDatasetAssociation) -> Optional[str]:
        """Tries to guess the name of the fake job from the dataset associations."""
        if dataset.copied_from_history_dataset_association:
            return "Import from History"
        if dataset.copied_from_library_dataset_dataset_association:
            return "Import from Library"
        return None


class DatasetCollectionCreationJob:
    def __init__(self, dataset_collection: HistoryDatasetCollectionAssociation) -> None:
        self.is_fake = True
        self.id = f"fake_{dataset_collection.id}"
        self.from_jobs: Optional[list[Job]] = None
        self.name = "Dataset Collection Creation"
        self.disabled_why = "Dataset collection created in a way not compatible with workflows"

    def set_jobs(self, jobs: list[Job]) -> None:
        assert jobs is not None
        self.from_jobs = jobs


def summarize(
    trans: ProvidesHistoryContext, history: Optional[History] = None
) -> tuple[dict[Any, list[tuple[Optional[str], HistoryItem]]], set[str]]:
    """Return mapping of job description to datasets for active items in
    supplied history - needed for building workflow from a history.

    Formerly call get_job_dict in workflow web controller.
    """
    summary = WorkflowSummary(trans, history)
    return summary.jobs, summary.warnings


class BaseWorkflowSummary:
    """Shared helpers for workflow extraction summaries (HID-based and ID-based)."""

    def __init__(self, trans: ProvidesHistoryContext) -> None:
        self.trans = trans
        self.warnings: set[str] = set()

    def _check_state(self, hda: HistoryDatasetAssociation) -> Optional[HistoryDatasetAssociation]:
        # FIXME: Create "Dataset.is_finished"
        if hda.state in ("new", "running", "queued"):
            self.warnings.add(WARNING_SOME_DATASETS_NOT_READY)
            return None
        return hda


class WorkflowSummary(BaseWorkflowSummary):
    def __init__(self, trans: ProvidesHistoryContext, history: Optional[History]) -> None:
        super().__init__(trans)
        if not history:
            history = trans.history
        assert history is not None
        self.history: History = history
        self.jobs: dict[Any, list[tuple[Optional[str], HistoryItem]]] = {}
        self.job_id2representative_job: dict[int, Job] = {}  # map a non-fake job id to its representative job
        self.implicit_map_jobs: list[Job] = []
        self.collection_types: dict[int, str] = {}

        self.hda_hid_in_history: dict[int, int] = {}
        self.hdca_hid_in_history: dict[int, int] = {}

        self.__summarize()

    def hid(self, content: HistoryItem) -> int:
        if content.history_content_type == "dataset_collection":
            if content.id in self.hdca_hid_in_history:
                return self.hdca_hid_in_history[content.id]
            elif content.history == self.history:
                assert content.hid is not None, f"HDCA {content.id} in history has no hid"
                return content.hid
            else:
                log.warning("extraction issue, using hdca hid from outside current history and unmapped")
                assert content.hid is not None, f"HDCA {content.id} from external history has no hid"
                return content.hid
        else:
            if content.id in self.hda_hid_in_history:
                return self.hda_hid_in_history[content.id]
            elif content.history == self.history:
                assert content.hid is not None, f"HDA {content.id} in history has no hid"
                return content.hid
            else:
                log.warning("extraction issue, using hda hid from outside current history and unmapped")
                assert content.hid is not None, f"HDA {content.id} from external history has no hid"
                return content.hid

    def __summarize(self) -> None:
        # Make a first pass handle all singleton jobs, input dataset and dataset collections
        # just grab the implicitly mapped jobs and handle in second pass. Second pass is
        # needed because cannot allow selection of individual datasets from an implicit
        # mapping during extraction - you get the collection or nothing.
        for content in self.history.visible_contents:
            self.__summarize_content(content)

    def __summarize_content(self, content: HistoryItem) -> None:
        # Update internal state for history content (either an HDA or
        # an HDCA).
        if content.history_content_type == "dataset_collection":
            self.__summarize_dataset_collection(cast(HistoryDatasetCollectionAssociation, content))
        else:
            self.__summarize_dataset(cast(HistoryDatasetAssociation, content))

    def __summarize_dataset_collection(self, dataset_collection: HistoryDatasetCollectionAssociation) -> None:
        hid_in_history = dataset_collection.hid
        assert hid_in_history is not None, f"HDCA {dataset_collection.id} has no hid"
        dataset_collection = _original_hdca(dataset_collection)
        self.hdca_hid_in_history[dataset_collection.id] = hid_in_history

        hid = dataset_collection.hid
        assert hid is not None, f"Original HDCA {dataset_collection.id} has no hid"
        self.collection_types[hid] = dataset_collection.collection.collection_type
        if cja := dataset_collection.creating_job_associations:
            # Use the "first" job to represent all mapped jobs.
            representative_assoc = cja[0]
            representative_job = representative_assoc.job
            if (
                representative_job not in self.jobs
                or self.jobs[representative_job][0][1].history_content_type == "dataset"
            ):
                self.jobs[representative_job] = [(representative_assoc.name, dataset_collection)]
                if dataset_collection.implicit_output_name:
                    self.implicit_map_jobs.append(representative_job)
            else:
                self.jobs[representative_job].append((representative_assoc.name, dataset_collection))
            for cja_assoc in cja:
                cja_job = cja_assoc.job
                self.job_id2representative_job[cja_job.id] = representative_job
        # Fallback for implicit output collections lacking creating_job_associations
        # (e.g. reached via Sentry GALAXY-MAIN-121W / issue #22359). Trace via a leaf
        # HDA's creating job instead.
        elif dataset_collection.implicit_output_name:
            # TODO: Optimize db call
            element = dataset_collection.collection.first_dataset_element
            dataset_instance = element.hda if element else None
            if not dataset_instance:
                # Got no dataset instance to walk back up to creating job
                # (empty collection, or leaf element is not an HDA - e.g. LDDA).
                # TODO track this via tool request model
                self.jobs[DatasetCollectionCreationJob(dataset_collection)] = [(None, dataset_collection)]
                return
            if not self._check_state(dataset_instance):
                # Just checking the state of one instance, don't need more but
                # makes me wonder if even need this check at all?
                return

            original_hda = _original_hda(dataset_instance)
            if not original_hda.creating_job_associations:
                log.warning(
                    "An implicitly create output dataset collection doesn't have a creating_job_association, should not happen!"
                )
                self.jobs[DatasetCollectionCreationJob(dataset_collection)] = [(None, dataset_collection)]

            for assoc in original_hda.creating_job_associations:
                job = assoc.job
                if job not in self.jobs or self.jobs[job][0][1].history_content_type == "dataset":
                    self.jobs[job] = [(assoc.name, dataset_collection)]
                    self.job_id2representative_job[job.id] = job
                    self.implicit_map_jobs.append(job)
                else:
                    self.jobs[job].append((assoc.name, dataset_collection))
        else:
            self.jobs[DatasetCollectionCreationJob(dataset_collection)] = [(None, dataset_collection)]

    def __summarize_dataset(self, dataset: HistoryDatasetAssociation) -> None:
        if not self._check_state(dataset):
            return

        hid_in_history = dataset.hid
        assert hid_in_history is not None
        original_hda = _original_hda(dataset)
        self.hda_hid_in_history[original_hda.id] = hid_in_history

        if not original_hda.creating_job_associations:
            self.jobs[FakeJob(dataset)] = [(None, dataset)]

        for assoc in original_hda.creating_job_associations:
            job = assoc.job
            if job in self.jobs:
                self.jobs[job].append((assoc.name, dataset))
            else:
                self.jobs[job] = [(assoc.name, dataset)]
                self.job_id2representative_job[job.id] = job


def step_inputs(trans: ProvidesHistoryContext, job: Job) -> tuple[ToolInputs, DataInputAssociations]:
    tool = trans.app.toolbox.get_tool(job.tool_id, tool_version=job.tool_version)
    assert tool is not None, f"Tool {job.tool_id} (version {job.tool_version}) not found"
    param_values = tool.get_param_values(
        job, ignore_errors=True
    )  # If a tool was updated and e.g. had a text value changed to an integer, we don't want a traceback here
    associations = __cleanup_param_values(tool.inputs, param_values)
    tool_inputs = tool.params_to_strings(param_values, trans.app)
    return tool_inputs, associations


def _walk_data_param_tree(
    inputs: ToolInputs,
    values: ToolInputs,
    leaf_handler: Callable[[Any, Any, str], None],
) -> None:
    """Walk a tool input tree, invoking ``leaf_handler`` once per
    Data/DataCollection leaf with ``(input, value, full_key)``.

    Clears the leaf's value in place and removes the deprecated metadata
    cruft (``<key>_*`` siblings of the formal input keys) the framework
    pushes into the root values dict. The cruft cleanup is shared because
    both extraction variants need it; only the per-leaf association
    emission differs.
    """
    if "dbkey" in values:
        del values["dbkey"]
    root_values = values
    root_input_keys = inputs.keys()

    def walk(prefix: str, inputs: ToolInputs, values: ToolInputs) -> None:
        for key, input in inputs.items():
            if isinstance(input, (DataToolParameter, DataCollectionToolParameter)):
                leaf_handler(input, values[key], prefix + key)
                values[key] = None
                # FIXME: Nested data params leak deprecated metadata into the
                # root values dict; scrub anything starting with `<key>_` that
                # isn't itself a formal input.
                cruft_prefix = f"{prefix + key}_"
                for k in list(root_values.keys()):
                    if k not in root_input_keys and k.startswith(cruft_prefix):
                        del root_values[k]
            elif isinstance(input, Repeat):
                if key in values:
                    group_values = values[key]
                    for i, rep_values in enumerate(group_values):
                        rep_index = rep_values["__index__"]
                        walk(f"{prefix}{key}_{rep_index}|", input.inputs, group_values[i])
            elif isinstance(input, Conditional):
                # __job_resource is a runtime-only group; strip and stop —
                # workflow encoding shouldn't carry resource selections.
                if input.name == "__job_resource":
                    if input.name in values:
                        del values[input.name]
                    return
                if input.name in values:
                    group_values = values[input.name]
                    current_case = group_values["__current_case__"]
                    walk(f"{prefix}{key}|", input.cases[current_case].inputs, group_values)
            elif isinstance(input, Section):
                if input.name in values:
                    walk(f"{prefix}{key}|", input.inputs, values[input.name])

    walk("", inputs, values)


def __cleanup_param_values(inputs: ToolInputs, values: ToolInputs) -> DataInputAssociations:
    """HID-keyed Data-leaf scrub: emit ``(hid, key)`` associations."""
    associations: DataInputAssociations = []

    def emit(input, value, key):
        for item in listify(value):
            if isinstance(item, model.DatasetCollectionElement):
                item = item.first_dataset_instance()
            if item:  # false for a non-set optional dataset
                associations.append((item.hid, key))

    _walk_data_param_tree(inputs, values, emit)
    return associations


def extract_workflow_by_ids(
    trans: ProvidesHistoryContext,
    user: User,
    workflow_name: str,
    job_manager: JobManager,
    job_ids: Optional[list[int]] = None,
    implicit_collection_jobs_ids: Optional[list[int]] = None,
    hda_ids: Optional[list[int]] = None,
    hdca_ids: Optional[list[int]] = None,
    tool_request_ids: Optional[list[int]] = None,
    dataset_names: Optional[list[str]] = None,
    dataset_collection_names: Optional[list[str]] = None,
) -> StoredWorkflow:
    """ID-based variant of :func:`extract_workflow`."""
    steps = extract_steps_by_ids(
        trans,
        job_manager=job_manager,
        job_ids=job_ids,
        implicit_collection_jobs_ids=implicit_collection_jobs_ids,
        hda_ids=hda_ids,
        hdca_ids=hdca_ids,
        tool_request_ids=tool_request_ids,
        dataset_names=dataset_names,
        dataset_collection_names=dataset_collection_names,
    )
    return _finalize_workflow(trans, user, workflow_name, steps)


IdKey = tuple[Literal["dataset", "collection"], int]
IdAssociations = list[tuple[IdKey, str]]


@dataclass
class _WorkItem:
    """One tool step to extract. ``job`` is ``None`` for a tool-request
    sourced step (e.g. an empty map-over that expanded to zero jobs); such a
    step is described entirely by ``request_payload`` + ``tool`` + the tool
    request's implicit output collections. ``sort_key`` orders producers
    before consumers (job id, or tool request id when jobless).
    """

    sort_key: int
    request_payload: Optional[dict]
    tool: Optional[Any]  # resolved Tool; None only on the legacy-fallback job path
    job: Optional[Job] = None
    output_hdcas: list[HistoryDatasetCollectionAssociation] = field(default_factory=list)
    tool_request: Optional[ToolRequest] = None  # set => tool-request sourced (possibly jobless)


def _data_input_step(name: str, step_labels: set[str]) -> WorkflowStep:
    step = model.WorkflowStep()
    step.type = "data_input"
    if name not in step_labels:
        step.label = name
        step_labels.add(name)
    step.tool_inputs = dict(name=name)
    return step


def _data_collection_input_step(name: str, collection_type: str, step_labels: set[str]) -> WorkflowStep:
    step = model.WorkflowStep()
    step.type = "data_collection_input"
    if name not in step_labels:
        step.label = name
        step_labels.add(name)
    step.tool_inputs = dict(name=name, collection_type=collection_type)
    return step


def _tool_for_job(trans: ProvidesHistoryContext, job: Job):
    tool = trans.app.toolbox.get_tool(job.tool_id, tool_version=job.tool_version)
    assert tool is not None, f"Tool {job.tool_id} (version {job.tool_version}) not found"
    return tool


def _tool_from_request(trans: ProvidesHistoryContext, tool_request: ToolRequest):
    """Rebuild the tool from the request's persisted ToolSource blob via the
    same reconstruction function the celery queue_jobs task uses (no toolbox,
    no job), so a jobless tool request still yields the parameter model
    extraction needs. The persisted ToolSource carries only source +
    source_class -- tool_dir/guid (which celery passes from the live tool at
    request time) are unavailable here; sufficient for built-in tools, the
    installed-tool/macro edge is a documented deferred follow-up.
    """
    tool_source = tool_request.tool_source
    return create_tool_from_representation(
        trans.app,
        tool_source.source,
        tool_dir=None,
        tool_source_class=tool_source.source_class,
        guid=None,
    )


def _tool_request_work_item(trans: ProvidesHistoryContext, tool_request: ToolRequest) -> _WorkItem:
    return _WorkItem(
        sort_key=tool_request.id,
        request_payload=_tool_request_payload(tool_request),
        tool=_tool_from_request(trans, tool_request),
        job=None,
        output_hdcas=[a.dataset_collection for a in tool_request.implicit_collections],
        tool_request=tool_request,
    )


def _synthesize_request_input_steps(
    trans: ProvidesHistoryContext,
    request_payload: dict,
    step_labels: set[str],
    id_to_output_pair: dict[IdKey, tuple[WorkflowStep, str]],
) -> list[WorkflowStep]:
    """For a tool-request sourced step, inputs the request references that are
    not produced by another selected step become workflow inputs. Mirrors
    :func:`_url_input_steps_for_request` ({src:url}) for {src:hda|hdca|dce}.
    Keys are computed exactly as :func:`_association_for_request_ref` so the
    synthesized input and the association connect to the same node.
    """
    sa_session = trans.sa_session
    created: list[WorkflowStep] = []
    for ref in request_internal_input_refs(request_payload):
        if ref.content_type == "collection":
            hdca = sa_session.get(HistoryDatasetCollectionAssociation, ref.id)
            if hdca is None:
                continue
            original_hdca = _original_hdca(hdca)
            key: IdKey = ("collection", original_hdca.id)
            if key in id_to_output_pair:
                continue
            step = _data_collection_input_step(ref.input_name, original_hdca.collection.collection_type, step_labels)
        else:
            if ref.content_type == "dataset_collection_element":
                dce = sa_session.get(model.DatasetCollectionElement, ref.id)
                leaf = (dce.hda or dce.first_dataset_instance()) if dce is not None else None
                hda = leaf if isinstance(leaf, HistoryDatasetAssociation) else None
            else:
                hda = sa_session.get(HistoryDatasetAssociation, ref.id)
            if hda is None:
                continue
            original_hda = _original_hda(hda)
            key = ("dataset", original_hda.id)
            if key in id_to_output_pair:
                continue
            step = _data_input_step(ref.input_name, step_labels)
        id_to_output_pair[key] = (step, "output")
        created.append(step)
    return created


def extract_steps_by_ids(
    trans: ProvidesHistoryContext,
    job_manager: Optional[JobManager] = None,
    job_ids: Optional[list[int]] = None,
    implicit_collection_jobs_ids: Optional[list[int]] = None,
    hda_ids: Optional[list[int]] = None,
    hdca_ids: Optional[list[int]] = None,
    tool_request_ids: Optional[list[int]] = None,
    dataset_names: Optional[list[str]] = None,
    dataset_collection_names: Optional[list[str]] = None,
) -> list[WorkflowStep]:
    """ID-based variant of :func:`extract_steps`.

    Inputs are decoded DB ids; each is fetched and access-checked against the
    current user via the appropriate manager. Connections are keyed by
    ``(content_type, db_id)`` of the resolved *original* HDA/HDCA so that
    copied datasets and cross-history items map deterministically.

    Mapped (map-over) steps are passed as ``implicit_collection_jobs_ids``;
    each ICJ becomes a single workflow step whose inputs are wired to the
    pre-map input HDCA(s) via ``ImplicitlyCreatedDatasetCollectionInput``.

    ``tool_request_ids`` sources a step from its (validated) tool request
    rather than a job, so an execution with zero jobs -- e.g. a map-over of
    an empty collection (#21788) -- still extracts a structurally-complete
    step; inputs the request references become workflow inputs.

    ``job_manager`` may be omitted only when ``job_ids`` is empty (kept
    Optional for unit-test ergonomics).
    """
    job_ids = list(job_ids or [])
    implicit_collection_jobs_ids = list(implicit_collection_jobs_ids or [])
    hda_ids = list(hda_ids or [])
    hdca_ids = list(hdca_ids or [])
    tool_request_ids = list(tool_request_ids or [])

    user = getattr(trans, "user", None)
    sa_session = trans.sa_session
    hda_manager = trans.app.hda_manager
    dataset_collection_manager = trans.app.dataset_collection_manager

    steps: list[WorkflowStep] = []
    step_labels: set[str] = set()
    id_to_output_pair: dict[IdKey, tuple[WorkflowStep, str]] = {}

    for i, hda_id in enumerate(hda_ids):
        hda = hda_manager.get_accessible(hda_id, user)
        name = dataset_names[i] if dataset_names else "Input Dataset"
        step = _data_input_step(name, step_labels)
        steps.append(step)
        original = _original_hda(hda)
        id_to_output_pair[("dataset", original.id)] = (step, "output")

    for i, hdca_id in enumerate(hdca_ids):
        hdca = dataset_collection_manager.get_dataset_collection_instance(trans, "history", hdca_id)
        name = dataset_collection_names[i] if dataset_collection_names else "Input Dataset Collection"
        step = _data_collection_input_step(name, hdca.collection.collection_type, step_labels)
        steps.append(step)
        original_hdca = _original_hdca(hdca)
        id_to_output_pair[("collection", original_hdca.id)] = (step, "output")

    # Each work item is one tool step to extract. The tool is resolved here
    # (caller-side): from the toolbox for job/ICJ items, rebuilt from the
    # persisted ToolSource for tool-request items -- the structured helpers
    # below stay job-free. request_payload is the structured request_internal
    # state when the execution has an unambiguous tool request, else None
    # (legacy fallback). Service-layer validator ensures no job in job_ids
    # has an ICJ association, so that branch handles only true plain jobs.
    work_items: list[_WorkItem] = []

    for job_id in job_ids:
        assert job_manager is not None, "job_manager required when job_ids supplied"
        job = job_manager.get_accessible_job(trans, job_id)
        request_payload = _structured_request_payload(job)
        work_items.append(
            _WorkItem(
                sort_key=job.id,
                request_payload=request_payload,
                tool=_tool_for_job(trans, job) if request_payload is not None else None,
                job=job,
            )
        )

    # NOTE: executions without a structured request still read parameters
    # via the legacy representative-job param walk in
    # _legacy_step_inputs_by_id; that path remains lossy for YAML / user-
    # defined tools and is gated behind
    # workflow_extraction_fallback_to_legacy_state.
    for icj_id in implicit_collection_jobs_ids:
        # Service-layer validator already checked existence, populated_state,
        # output-HDCA presence, and per-HDCA accessibility.
        icj = sa_session.get(ImplicitCollectionJobs, icj_id)
        assert icj is not None, f"ImplicitCollectionJobs {icj_id} not found"
        output_hdcas = icj.output_dataset_collection_instances
        if icj.jobs:
            representative_job = icj.representative_job
            request_payload = _structured_request_payload(icj=icj)
            work_items.append(
                _WorkItem(
                    sort_key=representative_job.id,
                    request_payload=request_payload,
                    tool=_tool_for_job(trans, representative_job) if request_payload is not None else None,
                    job=representative_job,
                    output_hdcas=output_hdcas,
                )
            )
        else:
            # Jobless map-over (e.g. an empty collection): there is no
            # representative job -- source the step from the tool request
            # reached via the output HDCA rather than crashing.
            tool_request = next(
                (
                    o.tool_request_association.tool_request
                    for o in output_hdcas
                    if o.tool_request_association is not None
                ),
                None,
            )
            if tool_request is None:
                raise exceptions.RequestParameterInvalidException(
                    f"ImplicitCollectionJobs {icj_id} has no jobs and no tool request to extract from"
                )
            work_items.append(_tool_request_work_item(trans, tool_request))

    for tool_request_id in tool_request_ids:
        tool_request = sa_session.get(ToolRequest, tool_request_id)
        assert tool_request is not None, f"ToolRequest {tool_request_id} not found"
        work_items.append(_tool_request_work_item(trans, tool_request))

    # Within a single id space, ids are monotonically assigned, so sorting by
    # sort_key produces dependency order: a downstream step always has a
    # larger key than the steps whose outputs it consumes. Job-sourced and
    # tool-request-sourced items use different id spaces (Job.id vs
    # ToolRequest.id) and are NOT comparable -- the service-layer validator
    # rejects payloads that mix them, so every item here shares one space.
    work_items.sort(key=lambda item: item.sort_key)
    fallback_to_legacy_state = getattr(
        getattr(trans.app, "config", None), "workflow_extraction_fallback_to_legacy_state", True
    )

    for item in work_items:
        job = item.job
        request_payload = item.request_payload
        tool_inputs, associations = step_inputs_by_id(
            trans,
            job,
            request_payload=request_payload,
            fallback_to_legacy_state=fallback_to_legacy_state,
            tool=item.tool,
        )
        step = model.WorkflowStep()
        step.type = "tool"
        if job is not None:
            step.tool_id = job.tool_id
            step.tool_version = job.tool_version
        else:
            assert item.tool is not None
            step.tool_id = item.tool.id
            step.tool_version = item.tool.version
        step.tool_inputs = tool_inputs

        if request_payload is not None:
            for input_name, url_step in _url_input_steps_for_request(trans, request_payload, step_labels):
                steps.append(url_step)
                _connect(step, input_name, (url_step, "output"))
            if item.tool_request is not None:
                # Tool-request sourced: referenced inputs not produced by
                # another selected step become workflow inputs.
                for input_step in _synthesize_request_input_steps(
                    trans, request_payload, step_labels, id_to_output_pair
                ):
                    steps.append(input_step)

        mapped_inputs: dict[str, HistoryDatasetCollectionAssociation] = {}
        if item.output_hdcas:
            for icol in item.output_hdcas[0].implicit_input_collections:
                if icol.name and icol.input_dataset_collection is not None:
                    mapped_inputs[icol.name] = _original_hdca(icol.input_dataset_collection)

        for key, input_name in associations:
            if input_name in mapped_inputs:
                key = ("collection", mapped_inputs[input_name].id)
            if key in id_to_output_pair:
                _connect(step, input_name, id_to_output_pair[key])
        steps.append(step)

        if item.tool_request is not None:
            for assoc in item.tool_request.implicit_collections:
                output_hdca = assoc.dataset_collection
                if output_hdca is None:
                    continue
                original_output = _original_hdca(output_hdca)
                id_to_output_pair[("collection", original_output.id)] = (step, assoc.output_name)
        elif item.output_hdcas:
            seen_names: dict[str, HistoryDatasetCollectionAssociation] = {}
            for output_hdca in item.output_hdcas:
                output_name = output_hdca.implicit_output_name
                if output_name and output_name not in seen_names:
                    seen_names[output_name] = output_hdca
            for output_name, output_hdca in seen_names.items():
                original_output = _original_hdca(output_hdca)
                id_to_output_pair[("collection", original_output.id)] = (step, output_name)
        else:
            assert job is not None
            for hda_assoc in job.output_datasets:
                hda_assoc_name = hda_assoc.name
                if _skip_output_assoc_name(hda_assoc_name):
                    continue
                original_hda = _original_hda(hda_assoc.dataset)
                id_to_output_pair[("dataset", original_hda.id)] = (step, hda_assoc_name)
            for hdca_assoc in job.output_dataset_collection_instances:
                original_hdca = _original_hdca(hdca_assoc.dataset_collection_instance)
                id_to_output_pair[("collection", original_hdca.id)] = (step, hdca_assoc.name)

    return steps


def step_inputs_by_id(
    trans: ProvidesHistoryContext,
    job: Optional[Job] = None,
    request_payload: Optional[dict] = None,
    fallback_to_legacy_state: bool = True,
    tool: Optional[Any] = None,
) -> tuple[ToolInputs, IdAssociations]:
    """ID-based variant of :func:`step_inputs`.

    ``request_payload`` is the structured request_internal state for this
    execution (resolved by the caller via :func:`_structured_request_payload`)
    or ``None`` when the execution has no unambiguous structured request. The
    seam is source-neutral by design: it is a payload dict, not a
    ``ToolRequest`` object, so a future resolver can supply the same payload
    from another backing store without changing this contract.

    ``tool`` is resolved by the caller (toolbox for job/ICJ items, rebuilt
    from the persisted ToolSource for tool-request items) so the structured
    path carries no job dependency -- ``job`` is ``None`` for a tool-request
    sourced (possibly jobless) step. The legacy fallback still needs a job.

    Returns associations keyed by ``(content_type, db_id)`` tuples (against
    the *original* HDA/HDCA after walking ``copied_from_*``). Collection
    and DCE inputs come from ``Job.input_dataset_collections`` /
    ``Job.input_dataset_collection_elements`` directly rather than from the
    param-value walk, which avoids the HID path's flattening of HDCAs to
    leaf HDAs and prevents duplicate emission for DCE-as-data-param.
    """
    if request_payload is not None:
        assert tool is not None, "structured workflow extraction requires the caller-resolved tool"
        return _structured_step_inputs_by_id(trans, tool, request_payload)
    assert job is not None, "legacy workflow extraction state requires a job"
    if not fallback_to_legacy_state:
        raise exceptions.RequestParameterInvalidException(
            f"Job {job.id} has no unambiguous tool request; legacy workflow extraction state fallback is disabled"
        )
    _record_legacy_state_fallback(trans, job)
    return _legacy_step_inputs_by_id(trans, job)


def _legacy_step_inputs_by_id(trans: ProvidesHistoryContext, job: Job) -> tuple[ToolInputs, IdAssociations]:
    tool = trans.app.toolbox.get_tool(job.tool_id, tool_version=job.tool_version)
    assert tool is not None, f"Tool {job.tool_id} (version {job.tool_version}) not found"
    param_values = tool.get_param_values(job, ignore_errors=True)
    associations: IdAssociations = __cleanup_param_values_by_id(tool.inputs, param_values)
    for assoc in job.input_dataset_collections:
        original_hdca = _original_hdca(assoc.dataset_collection)
        associations.append((("collection", original_hdca.id), assoc.name))
    for elem_assoc in job.input_dataset_collection_elements:
        dce = elem_assoc.dataset_collection_element
        leaf = dce.hda or dce.first_dataset_instance()
        if not isinstance(leaf, HistoryDatasetAssociation):
            continue
        original_hda = _original_hda(leaf)
        associations.append((("dataset", original_hda.id), elem_assoc.name))
    tool_inputs = tool.params_to_strings(param_values, trans.app)
    return tool_inputs, associations


def _structured_step_inputs_by_id(
    trans: ProvidesHistoryContext,
    tool: Any,
    request_payload: dict,
) -> tuple[ToolInputs, IdAssociations]:
    if tool.parameters is None:
        raise RequestInternalToWorkflowStateError(f"Tool {tool.id} has no parameter model for workflow extraction")
    parameter_bundle = ToolParameterBundleModel(parameters=tool.parameters)
    request_internal_state = RequestInternalToolState(request_payload)
    request_internal_state.validate(parameter_bundle, f"{tool.id} (request internal model)")
    workflow_state = to_workflow_step_state(request_internal_state, parameter_bundle)
    associations = _structured_request_associations_by_id(trans, request_payload)
    return workflow_state.input_state, associations


def _structured_request_payload(
    job: Optional[Job] = None,
    icj: Optional[ImplicitCollectionJobs] = None,
) -> Optional[dict]:
    """Resolve the structured request_internal payload for a step execution.

    Single seam mapping an execution unit to its validated structured state.
    Returns the request_internal dict when the execution has an unambiguous
    tool request, else ``None`` (caller falls back to legacy state). Returning
    a payload rather than a ``ToolRequest`` object keeps every downstream
    consumer source-neutral: a future resolver can source the same payload
    from another backing store by extending only this function.
    """
    tool_request = icj.tool_request if icj is not None else (job.tool_request if job is not None else None)
    if tool_request is None:
        return None
    return _tool_request_payload(tool_request)


def _tool_request_payload(tool_request: ToolRequest) -> dict:
    payload = json.loads(tool_request.request) if isinstance(tool_request.request, str) else tool_request.request
    if not isinstance(payload, dict):
        raise RequestInternalToWorkflowStateError(f"ToolRequest {tool_request.id} has malformed request payload")
    return payload


def _structured_request_associations_by_id(trans: ProvidesHistoryContext, request_payload: dict) -> IdAssociations:
    associations: IdAssociations = []
    for ref in request_internal_input_refs(request_payload):
        association = _association_for_request_ref(trans, ref)
        if association is not None:
            associations.append((association, ref.input_name))
    return associations


def _url_input_steps_for_request(
    trans: ProvidesHistoryContext,
    request_payload: dict,
    step_labels: set[str],
) -> list[tuple[str, WorkflowStep]]:
    return [
        (_url_input.input_name, _url_input_step(trans, _url_input, step_labels))
        for _url_input in request_internal_url_inputs(request_payload)
    ]


def _url_input_step(
    trans: ProvidesHistoryContext,
    url_input: RequestUrlInputRef,
    step_labels: set[str],
) -> WorkflowStep:
    step = model.WorkflowStep()
    step.type = "data_input"
    name = url_input.input_name or "URL Input Dataset"
    if name not in step_labels:
        step.label = name
        step_labels.add(name)
    step.tool_inputs = dict(name=name)
    _annotate_step(step, getattr(trans, "user", None), json.dumps(url_input.request, sort_keys=True))
    return step


def _annotate_step(step: WorkflowStep, user: Optional[User], annotation: str) -> None:
    assoc = model.WorkflowStepAnnotationAssociation()
    assoc.annotation = annotation
    assoc.user = user
    step.annotations = [assoc]


def _association_for_request_ref(trans: ProvidesHistoryContext, ref: RequestInputRef) -> Optional[IdKey]:
    sa_session = trans.sa_session
    if ref.content_type == "dataset":
        hda = sa_session.get(HistoryDatasetAssociation, ref.id)
        if hda is not None:
            return ("dataset", _original_hda(hda).id)
    elif ref.content_type == "collection":
        hdca = sa_session.get(HistoryDatasetCollectionAssociation, ref.id)
        if hdca is not None:
            return ("collection", _original_hdca(hdca).id)
    elif ref.content_type == "dataset_collection_element":
        dce = sa_session.get(model.DatasetCollectionElement, ref.id)
        if dce is not None:
            leaf = dce.hda or dce.first_dataset_instance()
            if isinstance(leaf, HistoryDatasetAssociation):
                return ("dataset", _original_hda(leaf).id)
    log.warning("Workflow extraction could not resolve request input ref %s", ref)
    return None


def _record_legacy_state_fallback(trans: ProvidesHistoryContext, job: Job) -> None:
    log.warning(
        "Workflow extraction falling back to legacy job state for job_id=%s history_id=%s",
        job.id,
        job.history_id,
    )
    execution_timer_factory = getattr(trans.app, "execution_timer_factory", None)
    statsd_client = getattr(execution_timer_factory, "galaxy_statsd_client", None)
    if statsd_client is not None:
        statsd_client.incr("galaxy.workflow_extraction.legacy_state_fallback")


def _original_hda(hda: HistoryDatasetAssociation) -> HistoryDatasetAssociation:
    while hda.copied_from_history_dataset_association:
        hda = hda.copied_from_history_dataset_association
    return hda


def _original_hdca(hdca: HistoryDatasetCollectionAssociation) -> HistoryDatasetCollectionAssociation:
    while hdca.copied_from_history_dataset_collection_association:
        hdca = hdca.copied_from_history_dataset_collection_association
    return hdca


def __cleanup_param_values_by_id(inputs: ToolInputs, values: ToolInputs) -> IdAssociations:
    """ID-keyed Data-leaf scrub.

    HDA leaves emit ``("dataset", _original_hda(hda).id)``. DCE values and
    ``DataCollectionToolParameter`` leaves are scrubbed but emit nothing —
    collection / DCE inputs are appended in :func:`step_inputs_by_id` from
    typed DB rows so HDCAs aren't lost to ``first_dataset_instance()``
    flattening and DCEs aren't double-emitted alongside their typed
    ``input_dataset_collection_elements`` row.
    """
    associations: IdAssociations = []

    def emit(input, value, key):
        if isinstance(input, DataCollectionToolParameter):
            return
        for item in listify(value):
            if isinstance(item, model.DatasetCollectionElement):
                # Covered by job.input_dataset_collection_elements; skip to
                # avoid duplicate connections.
                continue
            if isinstance(item, HistoryDatasetAssociation):
                original = _original_hda(item)
                associations.append((("dataset", original.id), key))

    _walk_data_param_tree(inputs, values, emit)
    return associations


__all__ = (
    "summarize",
    "extract_workflow",
    "extract_workflow_by_ids",
    "extract_steps_by_ids",
)
