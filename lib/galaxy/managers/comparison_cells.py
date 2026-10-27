"""Batch loading of job, step and dataset records and comparison cell builders."""

import logging
from collections import defaultdict
from collections.abc import (
    Collection,
    Iterable,
)
from typing import (
    Any,
    Literal,
    NamedTuple,
)

from sqlalchemy import select
from sqlalchemy.orm import (
    joinedload,
    undefer,
)

from galaxy.managers.comparison_columns import multiple_input_aliases
from galaxy.managers.hdas import HDASerializer
from galaxy.managers.histories import HistoryManager
from galaxy.model import (
    DatasetCollectionElement,
    HistoryDatasetAssociation,
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
)
from galaxy.model.metadata import (
    FileParameter,
    PythonObjectParameter,
)
from galaxy.model.scoped_session import galaxy_scoped_session
from galaxy.model.security import GalaxyRBACAgent
from galaxy.schema.comparisons import (
    CollectionCell,
    DatasetCell,
    MissingCell,
    ValueCell,
)
from galaxy.workflow.modules import read_expression_json

log = logging.getLogger(__name__)

COMPARISON_INLINE_EXPRESSION_MAX_BYTES = 4096
COMPARISON_METADATA_MAX_ITEMS = 50
NON_SCALAR_METADATA_PARAMS = (FileParameter, PythonObjectParameter)
JOB_RECORD_COLUMNS = (Job.id, Job.state, Job.tool_id, Job.tool_version, Job.copied_from_job_id.is_not(None))


class ItemRef(NamedTuple):
    src: Literal["hda", "hdca"]
    id: int


class ComparisonAccess(NamedTuple):
    """Who is asking; items they can't access render as missing."""

    user_id: int
    role_ids: frozenset[int]
    is_admin: bool


class ItemCell(NamedTuple):
    cell: DatasetCell | CollectionCell | ValueCell | MissingCell
    metadata_keys: list[str]


class JobRecord(NamedTuple):
    id: int
    state: str
    tool_id: str | None
    tool_version: str | None
    copied: bool


class ImplicitCollectionJobsRecord(NamedTuple):
    id: int
    populated_state: str
    representative: JobRecord | None
    states: dict[str, int]
    job_count: int
    copied_count: int


class ComparisonCellBuilder:
    def __init__(
        self,
        sa_session: galaxy_scoped_session,
        hda_serializer: HDASerializer,
        security_agent: GalaxyRBACAgent,
        history_manager: HistoryManager,
    ):
        self.sa_session = sa_session
        self.hda_serializer = hda_serializer
        self.security_agent = security_agent
        self.history_manager = history_manager

    def item_cells(
        self,
        refs: Iterable[ItemRef],
        access: ComparisonAccess,
        metadata_elements: list[str],
        inline_expression_values: bool,
    ) -> dict[ItemRef, ItemCell]:
        """Cells of the items that exist, with the caller's access checked once for the whole batch."""
        hdas, hdcas = self.load_items(refs, with_metadata=bool(metadata_elements))
        accessible_dataset_ids, accessible_history_ids = self._accessible(hdas, hdcas, access)
        inaccessible = ItemCell(MissingCell(reason="inaccessible"), [])
        item_cells: dict[ItemRef, ItemCell] = {}
        for hda in hdas.values():
            if hda.dataset_id not in accessible_dataset_ids:
                item_cells[ItemRef("hda", hda.id)] = inaccessible
                continue
            cell = self.dataset_cell(hda, metadata_elements, inline_expression_values)
            item_cells[ItemRef("hda", hda.id)] = ItemCell(cell, self.metadata_keys(hda))
        for hdca in hdcas.values():
            if hdca.history_id not in accessible_history_ids:
                item_cells[ItemRef("hdca", hdca.id)] = inaccessible
                continue
            item_cells[ItemRef("hdca", hdca.id)] = ItemCell(self.collection_cell(hdca), [])
        return item_cells

    def _accessible(
        self,
        hdas: dict[int, HistoryDatasetAssociation],
        hdcas: dict[int, HistoryDatasetCollectionAssociation],
        access: ComparisonAccess,
    ) -> tuple[set[int], set[int]]:
        """Dataset ids and HDCA history ids the caller may see, by the HDA and HDCA show rules."""
        dataset_ids = {hda.dataset_id for hda in hdas.values() if hda.dataset_id is not None}
        history_ids = {hdca.history_id for hdca in hdcas.values() if hdca.history_id is not None}
        if access.is_admin:
            return dataset_ids, history_ids
        return (
            self.security_agent.accessible_dataset_ids(access.role_ids, dataset_ids),
            self.history_manager.accessible_history_ids(access.user_id, history_ids),
        )

    def load_jobs(self, job_ids: Collection[int]) -> dict[int, JobRecord]:
        if not job_ids:
            return {}
        stmt = select(*JOB_RECORD_COLUMNS).where(Job.id.in_(job_ids))
        return {row[0]: JobRecord(*row) for row in self.sa_session.execute(stmt)}

    def load_implicit_collection_jobs(self, icj_ids: Collection[int]) -> dict[int, ImplicitCollectionJobsRecord]:
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

    def job_inputs(self, job_ids: Collection[int]) -> dict[int, dict[str, ItemRef]]:
        """Input datasets and collections of each job, keyed by association name."""
        inputs: dict[int, dict[str, ItemRef]] = defaultdict(dict)
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
            aliases = multiple_input_aliases(by_name)
            for name, dataset_id in by_name.items():
                if name not in aliases:
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

    def implicit_collection_inputs(self, icj_ids: Collection[int]) -> dict[int, dict[str, ItemRef]]:
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

    def job_outputs(self, job_ids: Collection[int]) -> dict[int, dict[str, ItemRef]]:
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

    def implicit_collection_outputs(self, icj_ids: Collection[int]) -> dict[int, dict[str, ItemRef]]:
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

    def load_items(
        self, refs: Iterable[ItemRef], with_metadata: bool
    ) -> tuple[dict[int, HistoryDatasetAssociation], dict[int, HistoryDatasetCollectionAssociation]]:
        refs = list(refs)
        hda_ids = {ref.id for ref in refs if ref.src == "hda"}
        hdca_ids = {ref.id for ref in refs if ref.src == "hdca"}
        return self.load_hdas(hda_ids, with_metadata), self.load_hdcas(hdca_ids)

    def load_hdas(self, ids: Collection[int], with_metadata: bool) -> dict[int, HistoryDatasetAssociation]:
        if not ids:
            return {}
        options = [joinedload(HistoryDatasetAssociation.dataset)]
        if with_metadata:
            options.append(undefer(HistoryDatasetAssociation._metadata))
        stmt = select(HistoryDatasetAssociation).options(*options).where(HistoryDatasetAssociation.id.in_(ids))
        return {hda.id: hda for hda in self.sa_session.scalars(stmt).unique()}

    def load_hdcas(self, ids: Collection[int]) -> dict[int, HistoryDatasetCollectionAssociation]:
        if not ids:
            return {}
        stmt = (
            select(HistoryDatasetCollectionAssociation)
            .options(joinedload(HistoryDatasetCollectionAssociation.collection))
            .where(HistoryDatasetCollectionAssociation.id.in_(ids))
        )
        return {hdca.id: hdca for hdca in self.sa_session.scalars(stmt).unique()}

    def metadata_keys(self, hda: HistoryDatasetAssociation) -> list[str]:
        """Metadata element names a dataset's datatype declares, without file or object values."""
        return [
            name for name, spec in hda.metadata.spec.items() if not isinstance(spec.param, NON_SCALAR_METADATA_PARAMS)
        ]

    def dataset_cell(
        self, hda: HistoryDatasetAssociation, metadata_elements: list[str], inline_expression_values: bool
    ) -> DatasetCell | ValueCell:
        if inline_expression_values:
            value_cell = self._expression_value_cell(hda)
            if value_cell:
                return value_cell
        metadata: dict[str, Any] = {}
        if metadata_elements:
            included = set(metadata_elements).intersection(self.metadata_keys(hda))
            serialized = self.hda_serializer.serialize_metadata(hda, "metadata", included=included)
            metadata = {name: _cap(value) for name, value in serialized.items() if value is not None}
        return DatasetCell(
            id=hda.id,
            hid=hda.hid,
            name=hda.name,
            extension=hda.extension,
            state=hda.state,
            deleted=hda.deleted,
            purged=hda.purged,
            history_id=hda.history_id,
            metadata=metadata,
        )

    def collection_cell(self, hdca: HistoryDatasetCollectionAssociation) -> CollectionCell:
        collection = hdca.collection
        return CollectionCell(
            id=hdca.id,
            hid=hdca.hid,
            name=hdca.name,
            collection_type=collection.collection_type,
            element_count=collection.element_count,
            populated_state=collection.populated_state,
            deleted=hdca.deleted,
            history_id=hdca.history_id,
        )

    def _expression_value_cell(self, hda: HistoryDatasetAssociation) -> ValueCell | None:
        if hda.extension != "expression.json" or hda.state != "ok" or hda.purged:
            return None
        # size unknown without touching the object store
        if not hda.dataset or hda.dataset.file_size is None:
            return None
        if hda.dataset.get_size(calculate_size=False) > COMPARISON_INLINE_EXPRESSION_MAX_BYTES:
            return None
        try:
            value = read_expression_json(hda)
        except Exception:
            log.debug("Could not read expression.json dataset %s for a comparison cell", hda.id, exc_info=True)
            return None
        return ValueCell(value=value, source="expression_json", dataset_id=hda.id)


def _cap(value: Any) -> Any:
    if isinstance(value, (list, tuple)):
        return list(value[:COMPARISON_METADATA_MAX_ITEMS])
    if isinstance(value, dict):
        return dict(list(value.items())[:COMPARISON_METADATA_MAX_ITEMS])
    return value
