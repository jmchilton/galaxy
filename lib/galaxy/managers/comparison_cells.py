"""Comparison cells: datasets and collections as the caller may see them, and one cell per row and column."""

import logging
from collections import defaultdict
from collections.abc import (
    Collection,
    Container,
    Iterable,
    Mapping,
)
from typing import (
    Any,
    NamedTuple,
)

from sqlalchemy import select
from sqlalchemy.orm import (
    joinedload,
    undefer,
)

from galaxy.managers.comparison_records import (
    IoValue,
    ItemRef,
    ItemRefs,
)
from galaxy.managers.hdas import HDASerializer
from galaxy.managers.histories import HistoryManager
from galaxy.model import (
    HistoryDatasetAssociation,
    HistoryDatasetCollectionAssociation,
)
from galaxy.model.metadata import (
    FileParameter,
    PythonObjectParameter,
)
from galaxy.model.scoped_session import galaxy_scoped_session
from galaxy.model.security import GalaxyRBACAgent
from galaxy.schema.comparisons import (
    AnyComparisonCell,
    CollectionCell,
    ComparisonColumn,
    ComparisonQueryBase,
    DatasetCell,
    DatasetListCell,
    MissingCell,
    MissingReason,
    ValueCell,
)
from galaxy.workflow.modules import read_expression_json

log = logging.getLogger(__name__)

COMPARISON_INLINE_EXPRESSION_MAX_BYTES = 4096
COMPARISON_METADATA_MAX_ITEMS = 50
NON_SCALAR_METADATA_PARAMS = (FileParameter, PythonObjectParameter)


class ComparisonAccess(NamedTuple):
    """Who is asking; items they can't access render as missing."""

    user_id: int
    role_ids: frozenset[int]
    is_admin: bool


class ItemCell(NamedTuple):
    cell: DatasetCell | CollectionCell | ValueCell | MissingCell
    metadata_keys: list[str]


class RowIo(NamedTuple):
    """A row's io by column key, and what its empty columns show."""

    io: Mapping[str, IoValue]
    # keys of the columns the row's version has; None: every column
    in_version: Container[str] | None
    # why a column the row's version has is empty
    reason: MissingReason


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

    def row_cells(
        self, columns: list[ComparisonColumn], rows: list[RowIo], access: ComparisonAccess, query: ComparisonQueryBase
    ) -> list[dict[str, AnyComparisonCell]]:
        """Each row's cells, with every dataset and collection loaded and access-checked in one batch."""
        refs = (ref for row in rows for ref in item_refs(row.io))
        item_cells = self.item_cells(refs, access, query.metadata_elements, query.inline_expression_values)
        return fill_cells(columns, rows, item_cells)

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
        skipped = ItemCell(MissingCell(reason="skipped"), [])
        item_cells: dict[ItemRef, ItemCell] = {}
        for hda in hdas.values():
            if hda.dataset_id not in accessible_dataset_ids:
                item_cells[ItemRef("hda", hda.id)] = inaccessible
                continue
            # a skipped step's placeholder output, in every mode and wherever it is used
            if hda.is_skipped:
                item_cells[ItemRef("hda", hda.id)] = skipped
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
            self.history_manager.accessible_ids(access.user_id, history_ids),
        )

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
        # the datatype's spec, not hda.metadata, which loads the deferred metadata column
        spec = hda.datatype.metadata_spec
        return [name for name, element in spec.items() if not isinstance(element.param, NON_SCALAR_METADATA_PARAMS)]

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
        if not inlinable_expression(hda):
            return None
        try:
            value = read_expression_json(hda)
        except Exception:
            log.debug("Could not read expression.json dataset %s for a comparison cell", hda.id, exc_info=True)
            return None
        return ValueCell(value=value, source="expression_json", dataset_id=hda.id)


def inlinable_expression(hda: HistoryDatasetAssociation) -> bool:
    """Whether an ``expression.json`` dataset is ready and small enough to read into a cell."""
    if hda.extension != "expression.json" or hda.state != "ok" or hda.purged:
        return False
    # size unknown without touching the object store
    if not hda.dataset or hda.dataset.file_size is None:
        return False
    size: int = hda.dataset.get_size(calculate_size=False)
    return size <= COMPARISON_INLINE_EXPRESSION_MAX_BYTES


def _cap(value: Any) -> Any:
    if isinstance(value, (list, tuple)):
        return list(value[:COMPARISON_METADATA_MAX_ITEMS])
    if isinstance(value, dict):
        return dict(list(value.items())[:COMPARISON_METADATA_MAX_ITEMS])
    return value


def item_refs(io: Mapping[str, IoValue]) -> Iterable[ItemRef]:
    """Every dataset and collection a row's io refers to, multiple input members included."""
    for value in io.values():
        if isinstance(value, ItemRef):
            yield value
        elif isinstance(value, ItemRefs):
            yield from value.refs


def fill_cells(
    columns: list[ComparisonColumn], rows: list[RowIo], item_cells: Mapping[ItemRef, ItemCell]
) -> list[dict[str, AnyComparisonCell]]:
    """One cell per row and column; sets each column's ``metadata_keys`` from the datasets in it."""
    metadata_keys: dict[str, set[str]] = defaultdict(set)
    filled = [_row_cells(columns, row, item_cells, metadata_keys) for row in rows]
    for column in columns:
        column.metadata_keys = sorted(metadata_keys[column.key])
    return filled


def _row_cells(
    columns: list[ComparisonColumn],
    row: RowIo,
    item_cells: Mapping[ItemRef, ItemCell],
    metadata_keys: dict[str, set[str]],
) -> dict[str, AnyComparisonCell]:
    cells: dict[str, AnyComparisonCell] = {}
    for column in columns:
        value = row.io.get(column.key)
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
        in_row_version = row.in_version is None or column.key in row.in_version
        cells[column.key] = MissingCell(reason=row.reason if in_row_version else "not_in_version")
    return cells
