"""Bounded user-action provenance graph for Galaxy histories.

For each selected top-level history item, resolves its producing
structured request via the unified ``resolve_structured_request`` seam
and that producer's declared inputs from the submission payload, one
hop out from the seed.
"""

import logging
from typing import (
    Literal,
    Optional,
    Union,
)

from sqlalchemy import (
    or_,
    Select,
    select,
    union_all,
)
from sqlalchemy.orm import Session
from sqlalchemy.sql.expression import literal_column

from galaxy.exceptions import (
    MessageException,
    RequestParameterInvalidException,
)
from galaxy.managers.workflow_request_state import (
    resolve_structured_request,
    ResolvedStructuredRequest,
    tool_request_payload,
)
from galaxy.model import (
    Dataset,
    DatasetCollection,
    DatasetCollectionElement,
    HistoryDatasetAssociation,
    HistoryDatasetCollectionAssociation,
    Job,
    JobToOutputDatasetAssociation,
    JobToOutputDatasetCollectionAssociation,
    ToolRequest,
    ToolRequestImplicitCollectionAssociation,
    ToolSource,
)
from galaxy.schema.history_graph import (
    GraphEdge,
    GraphNode,
    HistoryGraphResponse,
    NodeRef,
    TruncationInfo,
)
from galaxy.schema.schema import TOOL_EXECUTION_STATE_ENCODE_KIND
from galaxy.security.idencoding import IdEncodingHelper
from galaxy.structured_app import MinimalManagerApp
from galaxy.tool_util.parameters import RequestInternalToWorkflowStateError
from galaxy.tool_util.parameters.request import request_internal_input_refs
from galaxy.tool_util.toolbox import AbstractToolBox

log = logging.getLogger(__name__)

TYPE_RANK = {"dataset": 0, "collection": 1, "tool_execution": 2}
EDGE_TYPE_RANK = {
    "dataset_input": 0,
    "dataset_output": 1,
    "collection_input": 2,
    "collection_output": 3,
    "dataset_element": 4,
}
# Internal node-type token -> public src value. The internal tokens
# ("dataset"/"collection") stay because they mirror request payload
# content_type; only the wire boundary speaks src.
NODE_SRC: dict[str, str] = {"dataset": "hda", "collection": "hdca", "tool_execution": "tool_execution"}
MAX_LIMIT = 1000

# Tool ids that represent infrastructure operations (uploads, metadata setting,
# etc.) rather than user-level lineage steps. Jobs with these tool_ids are
# excluded from producer lookups so they do not appear as nodes or edges.
SYNTHETIC_TOOL_IDS: tuple[str, ...] = ("__DATA_FETCH__",)


class HistoryGraphManager:
    def __init__(self, app: MinimalManagerApp):
        self.app = app

    def build(
        self,
        sa_session: Session,
        history_id: int,
        limit: int = 500,
        include_deleted: bool = False,
        seed: Optional[NodeRef] = None,
        direction: Literal["backward", "forward", "both"] = "both",
        depth: int = 5,
        seed_scope_hid: Optional[int] = None,
    ) -> HistoryGraphResponse:
        return HistoryGraphBuilder(
            sa_session=sa_session,
            security=self.app.security,
            toolbox=self.app.toolbox,
            history_id=history_id,
            limit=limit,
            include_deleted=include_deleted,
            seed=seed,
            direction=direction,
            depth=depth,
            seed_scope_hid=seed_scope_hid,
        ).build()


class HistoryGraphBuilder:
    """Builds a provenance graph from selected history items.

    Behaviors:
    - HDA producer edges come from JobToOutputDatasetAssociation joined
      to Job.
    - HDCA producer edges come from JobToOutputDatasetCollectionAssociation
      joined to Job, plus ToolRequestImplicitCollectionAssociation for
      jobless tool-request-backed collection outputs.
    - Input edges come from the resolved structured-request payload
      (ToolExecutionState for new executions, ToolRequest for historical
      pre-EXEC_STATE rows), reached uniformly via
      ``resolve_structured_request``.
    - When an item resolves to more than one distinct producer (keyed by
      ``(source, source_id)``), the item is kept as a node and the
      producer edge is skipped with a debug log.
    - Resolver-side malformed payloads are logged at debug level and the
      item becomes a node with no input edges.
    - Hidden HDAs that belong to a collection are filtered before
      producer lookup and surfaced via their parent HDCA instead.
    - ``limit`` is clamped to ``MAX_LIMIT`` to keep per-request work
      bounded regardless of caller input.
    """

    def __init__(
        self,
        sa_session: Session,
        security: IdEncodingHelper,
        history_id: int,
        limit: int = 500,
        toolbox: Optional[AbstractToolBox] = None,
        include_deleted: bool = False,
        seed: Optional[NodeRef] = None,
        direction: Literal["backward", "forward", "both"] = "both",
        depth: int = 5,
        seed_scope_hid: Optional[int] = None,
    ):
        self.sa_session = sa_session
        self.security = security
        self.history_id = history_id
        self.limit = min(limit, MAX_LIMIT)
        self.toolbox = toolbox
        self.include_deleted = include_deleted
        self.seed = seed
        self.direction = direction
        self.depth = depth
        self.seed_scope_hid = seed_scope_hid
        self._older_than_hid: Optional[int] = None
        self._newer_than_hid: Optional[int] = None
        self._sort_keys: dict[NodeRef, tuple[int, int]] = {}

    def build(self) -> HistoryGraphResponse:
        truncation = TruncationInfo()
        if self.seed_scope_hid is not None:
            truncation.scope_type = "seed_centered"
            half = self.limit // 2
            self._older_than_hid = self.seed_scope_hid + half + (self.limit % 2)
            self._newer_than_hid = self.seed_scope_hid - half - 1

        # 1. Select top-level items in scope.
        dataset_ids, collection_ids, item_capped = self._select_items()
        truncation.item_count_capped = item_capped

        # 2. Remove hidden collection elements.
        dataset_ids = self._remove_hidden_elements(dataset_ids)

        # 3. Single producer pass: every selected item resolves its producer
        #    via the unified seam. Two source kinds reach the wire:
        #    'tool_execution_state' (the EXEC_STATE walk, new executions) and
        #    'tool_request' (transitional historical fallback). Both render
        #    as wire src "tool_execution" - the source-kind distinction lives
        #    in the cipher kind, so same-pk rows in the two tables never
        #    collide.
        edges: list[GraphEdge] = []
        closure_dataset_ids: set[int] = set()
        closure_collection_ids: set[int] = set()

        producers, producer_meta, payloads = self._producers(dataset_ids, collection_ids)
        for item_key, producer_id in producers.items():
            item_type, item_id = item_key
            etype = "dataset_output" if item_type == "dataset" else "collection_output"
            edges.append(
                GraphEdge(
                    source=self._producer_ref(*producer_id),
                    target=self._ref(item_type, item_id),
                    type=etype,
                )
            )
        for producer_id, payload in payloads.items():
            self._emit_input_edges(
                self._producer_ref(*producer_id),
                payload,
                dataset_ids,
                collection_ids,
                edges,
                closure_dataset_ids,
                closure_collection_ids,
            )

        # Collection element membership: each visible HDA that is (transitively)
        # an element of a seed HDCA gets a ``dataset_element`` edge to that
        # HDCA, surfacing the build-collection-from-datasets step that has
        # no producer of its own. Scoped to seed ``collection_ids``, not the
        # payload-pulled closure HDCAs — bounds the walk to the user-visible
        # selection window.
        for hda_id, hdca_id in self._collection_element_edges(collection_ids):
            edges.append(
                GraphEdge(
                    source=self._ref("dataset", hda_id),
                    target=self._ref("collection", hdca_id),
                    type="dataset_element",
                )
            )
            if hda_id not in dataset_ids:
                closure_dataset_ids.add(hda_id)

        # 4. Filter closure items by the same deleted policy as seed selection.
        if not self.include_deleted and (closure_dataset_ids or closure_collection_ids):
            closure_dataset_ids = self._filter_deleted_ids(HistoryDatasetAssociation, closure_dataset_ids)
            closure_collection_ids = self._filter_deleted_ids(
                HistoryDatasetCollectionAssociation, closure_collection_ids
            )

        # Build nodes.
        all_dataset_ids = dataset_ids | closure_dataset_ids
        all_collection_ids = collection_ids | closure_collection_ids
        nodes: list[GraphNode] = []
        nodes.extend(self._dataset_nodes(all_dataset_ids))
        nodes.extend(self._collection_nodes(all_collection_ids))
        nodes.extend(self._producer_nodes(producer_meta))

        # Invariant: every edge endpoint must be a node. Edges were emitted
        # before closure deletion filtering, so drop any that now reference
        # an item that did not survive.
        node_id_set = {n.ref for n in nodes}
        edges = [e for e in edges if e.source in node_id_set and e.target in node_id_set]

        # 5. Resolve tool names.
        self._resolve_tool_names(nodes)

        # 6. Optional seed subgraph filter (in-memory only).
        if self.seed:
            node_ids = {n.ref for n in nodes}
            truncation.seed_in_scope = self.seed in node_ids
            nodes, edges = self._seed_filter(self.seed, nodes, edges)

        # 7. Sort.
        nodes, edges = self._sort(nodes, edges)
        return HistoryGraphResponse(nodes=nodes, edges=edges, truncated=truncation)

    # ── Item selection ──

    def _select_items(self) -> tuple[set[int], set[int], bool]:
        hda_q: Select = select(
            HistoryDatasetAssociation.id,
            HistoryDatasetAssociation.hid,
            literal_column("'dataset'").label("item_type"),
        ).where(HistoryDatasetAssociation.history_id == self.history_id)
        if not self.include_deleted:
            hda_q = hda_q.where(HistoryDatasetAssociation.deleted == False)  # noqa: E712
        if self._older_than_hid is not None:
            hda_q = hda_q.where(HistoryDatasetAssociation.hid < self._older_than_hid)
        if self._newer_than_hid is not None:
            hda_q = hda_q.where(HistoryDatasetAssociation.hid > self._newer_than_hid)

        hdca_q: Select = select(
            HistoryDatasetCollectionAssociation.id,
            HistoryDatasetCollectionAssociation.hid,
            literal_column("'collection'").label("item_type"),
        ).where(HistoryDatasetCollectionAssociation.history_id == self.history_id)
        if not self.include_deleted:
            hdca_q = hdca_q.where(HistoryDatasetCollectionAssociation.deleted == False)  # noqa: E712
        if self._older_than_hid is not None:
            hdca_q = hdca_q.where(HistoryDatasetCollectionAssociation.hid < self._older_than_hid)
        if self._newer_than_hid is not None:
            hdca_q = hdca_q.where(HistoryDatasetCollectionAssociation.hid > self._newer_than_hid)

        combined = union_all(hda_q, hdca_q).subquery()
        # Deterministic order: hid desc, then id desc as a stable tiebreaker
        # so duplicate hids (theoretically possible across imported data) do
        # not affect internal selection stability.
        stmt = (
            select(combined.c.id, combined.c.hid, combined.c.item_type)
            .order_by(combined.c.hid.desc(), combined.c.id.desc())
            .limit(self.limit + 1)
        )

        dataset_ids: set[int] = set()
        collection_ids: set[int] = set()
        count = 0
        for row in self.sa_session.execute(stmt):
            count += 1
            if count > self.limit:
                break
            if row.item_type == "dataset":
                dataset_ids.add(row.id)
            else:
                collection_ids.add(row.id)
        return dataset_ids, collection_ids, count > self.limit

    def _remove_hidden_elements(self, dataset_ids: set[int]) -> set[int]:
        if not dataset_ids:
            return dataset_ids
        stmt = (
            select(HistoryDatasetAssociation.id)
            .join(DatasetCollectionElement, DatasetCollectionElement.hda_id == HistoryDatasetAssociation.id)
            .where(
                HistoryDatasetAssociation.id.in_(dataset_ids),
                HistoryDatasetAssociation.visible == False,  # noqa: E712
            )
            .distinct()
        )
        to_remove = {row.id for row in self.sa_session.execute(stmt)}
        return dataset_ids - to_remove

    def _filter_deleted_ids(
        self,
        model_cls: Union[type[HistoryDatasetAssociation], type[HistoryDatasetCollectionAssociation]],
        ids: set[int],
    ) -> set[int]:
        """Return the subset of ``ids`` whose rows are not marked deleted.

        Used to apply the seed-side deleted policy to closure items
        pulled in via payload refs."""
        if not ids:
            return ids
        stmt = select(model_cls.id).where(
            model_cls.id.in_(ids),
            model_cls.deleted == False,  # noqa: E712
        )
        return {row.id for row in self.sa_session.execute(stmt)}

    # ── Producer lookup ──

    def _producers(
        self,
        dataset_ids: set[int],
        collection_ids: set[int],
    ) -> tuple[
        dict[tuple[str, int], tuple[str, int]],
        dict[tuple[str, int], Optional[str]],
        dict[tuple[str, int], dict],
    ]:
        """One pass: every producer execution -> structured request via the seam.

        Returns:
        - ``producers``: ``item_key -> (source, source_id)`` for items with
          exactly one distinct producing structured-request source. Items
          resolving to >1 distinct producer are dropped (and logged) -
          they remain as nodes without a producer edge.
        - ``producer_meta``: ``(source, source_id) -> tool_id`` for node
          construction.
        - ``payloads``: ``(source, source_id) -> dict`` for input-edge
          emission, sourced from the resolver (no per-source SQL).

        ``source`` is ``"tool_execution_state"`` (the EXEC_STATE walk) or
        ``"tool_request"`` (the transitional historical fallback for jobs
        whose TES is NULL). Jobs whose resolver returns ``None`` (no
        validated capture, no historical TR) contribute no producer.
        """
        producers: dict[tuple[str, int], tuple[str, int]] = {}
        producer_meta: dict[tuple[str, int], Optional[str]] = {}
        payloads: dict[tuple[str, int], dict] = {}
        if not dataset_ids and not collection_ids:
            return producers, producer_meta, payloads

        item_jobs: list[tuple[tuple[str, int], int, Optional[str]]] = []
        item_tool_requests: list[tuple[tuple[str, int], int, Optional[str]]] = []
        job_ids: set[int] = set()
        tool_request_ids: set[int] = set()
        if dataset_ids:
            stmt = (
                select(
                    JobToOutputDatasetAssociation.dataset_id.label("item_id"),
                    Job.id.label("job_id"),
                    Job.tool_id,
                )
                .join(Job, Job.id == JobToOutputDatasetAssociation.job_id)
                .where(
                    JobToOutputDatasetAssociation.dataset_id.in_(dataset_ids),
                    Job.tool_id.isnot(None),
                    Job.tool_id.notin_(SYNTHETIC_TOOL_IDS),
                )
            )
            for row in self.sa_session.execute(stmt):
                item_jobs.append((("dataset", row.item_id), row.job_id, row.tool_id))
                job_ids.add(row.job_id)
        if collection_ids:
            stmt = (
                select(
                    JobToOutputDatasetCollectionAssociation.dataset_collection_id.label("item_id"),
                    Job.id.label("job_id"),
                    Job.tool_id,
                )
                .join(Job, Job.id == JobToOutputDatasetCollectionAssociation.job_id)
                .where(
                    JobToOutputDatasetCollectionAssociation.dataset_collection_id.in_(collection_ids),
                    Job.tool_id.isnot(None),
                    Job.tool_id.notin_(SYNTHETIC_TOOL_IDS),
                )
            )
            for row in self.sa_session.execute(stmt):
                item_jobs.append((("collection", row.item_id), row.job_id, row.tool_id))
                job_ids.add(row.job_id)
            stmt = (
                select(
                    ToolRequestImplicitCollectionAssociation.dataset_collection_id.label("item_id"),
                    ToolRequest.id.label("tool_request_id"),
                    ToolSource.tool_id,
                )
                .join(ToolRequest, ToolRequest.id == ToolRequestImplicitCollectionAssociation.tool_request_id)
                .join(ToolSource, ToolSource.id == ToolRequest.tool_source_id)
                .where(
                    ToolRequestImplicitCollectionAssociation.dataset_collection_id.in_(collection_ids),
                    or_(ToolSource.tool_id.is_(None), ToolSource.tool_id.notin_(SYNTHETIC_TOOL_IDS)),
                )
            )
            for row in self.sa_session.execute(stmt):
                item_tool_requests.append((("collection", row.item_id), row.tool_request_id, row.tool_id))
                tool_request_ids.add(row.tool_request_id)
        if not job_ids and not tool_request_ids:
            return producers, producer_meta, payloads

        jobs = {j.id: j for j in self.sa_session.scalars(select(Job).where(Job.id.in_(job_ids)))} if job_ids else {}
        resolved_by_job: dict[int, Optional[ResolvedStructuredRequest]] = {}
        for job_id in job_ids:
            job = jobs.get(job_id)
            if job is None:
                resolved_by_job[job_id] = None
                continue
            icj_assoc = job.implicit_collection_jobs_association
            icj = icj_assoc.implicit_collection_jobs if icj_assoc is not None else None
            try:
                resolved = (
                    resolve_structured_request(icj=icj) if icj is not None else resolve_structured_request(job=job)
                )
            except RequestInternalToWorkflowStateError:
                log.debug("history_graph: malformed structured request for job %d", job_id)
                resolved = None
            resolved_by_job[job_id] = resolved

        tool_requests = (
            {
                tr.id: tr
                for tr in self.sa_session.scalars(select(ToolRequest).where(ToolRequest.id.in_(tool_request_ids)))
            }
            if tool_request_ids
            else {}
        )
        resolved_by_tool_request: dict[int, Optional[ResolvedStructuredRequest]] = {}
        for tool_request_id in tool_request_ids:
            tool_request = tool_requests.get(tool_request_id)
            if tool_request is None:
                resolved_by_tool_request[tool_request_id] = None
                continue
            try:
                resolved = ResolvedStructuredRequest(
                    "tool_request",
                    tool_request.id,
                    tool_request_payload(tool_request),
                )
            except RequestInternalToWorkflowStateError:
                log.debug("history_graph: malformed structured request for tool_request %d", tool_request_id)
                resolved = None
            resolved_by_tool_request[tool_request_id] = resolved

        # item_key -> {(source, source_id): tool_id}; ambiguity rule = >1 distinct.
        candidates: dict[tuple[str, int], dict[tuple[str, int], Optional[str]]] = {}
        for item_key, job_id, tool_id in item_jobs:
            resolved = resolved_by_job.get(job_id)
            if resolved is None:
                continue
            producer_id = (resolved.source, resolved.source_id)
            candidates.setdefault(item_key, {})[producer_id] = tool_id
            payloads.setdefault(producer_id, resolved.payload)
        for item_key, tool_request_id, tool_id in item_tool_requests:
            resolved = resolved_by_tool_request.get(tool_request_id)
            if resolved is None:
                continue
            producer_id = (resolved.source, resolved.source_id)
            candidates.setdefault(item_key, {})[producer_id] = tool_id
            payloads.setdefault(producer_id, resolved.payload)
        for item_key, producer_map in candidates.items():
            if len(producer_map) == 1:
                producer_id, tool_id = next(iter(producer_map.items()))
                producers[item_key] = producer_id
                producer_meta[producer_id] = tool_id
            else:
                log.debug(
                    "history_graph: skipping %s — ambiguous producer (%s)",
                    item_key,
                    set(producer_map.keys()),
                )
        return producers, producer_meta, payloads

    # ── Payload input resolution ──

    def _extract_inputs(self, payload: dict) -> set[tuple[str, int]]:
        """Sole payload entry point inside the builder. Walks a single
        ``tool_request.request`` payload and returns the deduplicated
        set of input refs the builder will emit edges for.

        Contract, in order:
        1. Extract declared ``{src, id}`` refs from the payload, using
           the same ``boltons.iterutils.remap`` traversal idiom as
           ``jobs.py::populate_input_data_input_id`` — when we hit a
           leaf keyed ``id``, we peek at its sibling ``src`` on the
           parent container to decide whether it is an HDA/HDCA ref.
        2. Normalize refs so that each one points at a top-level
           history item (see ``_normalize_refs``).
        3. Return as a set — the caller does not need to dedupe.

        Payload shape is trusted to be Pydantic-validated upstream when
        the tool_request was accepted; no explicit depth or ref caps are
        applied here by design."""
        refs = {(ref.content_type, ref.id) for ref in request_internal_input_refs(payload, {"hda", "hdca"})}
        return self._normalize_refs(refs)

    def _normalize_refs(self, refs: set[tuple[str, int]]) -> set[tuple[str, int]]:
        """Apply the single normalization rule: a hidden-element HDA
        ref is replaced with its parent HDCA. Single-hop only — the
        replacement is not re-normalized. No other rules apply here
        by design; adding more cases should be weighed against the
        invariant that every emitted ref points at a top-level item."""
        hda_ids = [item_id for t, item_id in refs if t == "dataset"]
        hdca_parents: dict[int, int] = {}
        if hda_ids:
            stmt = (
                select(
                    HistoryDatasetAssociation.id.label("hda_id"),
                    HistoryDatasetCollectionAssociation.id.label("hdca_id"),
                )
                .join(DatasetCollectionElement, DatasetCollectionElement.hda_id == HistoryDatasetAssociation.id)
                .join(
                    HistoryDatasetCollectionAssociation,
                    HistoryDatasetCollectionAssociation.collection_id == DatasetCollectionElement.dataset_collection_id,
                )
                .where(
                    HistoryDatasetAssociation.id.in_(hda_ids),
                    HistoryDatasetAssociation.visible == False,  # noqa: E712
                )
            )
            for row in self.sa_session.execute(stmt):
                hdca_parents[row.hda_id] = row.hdca_id

        result: set[tuple[str, int]] = set()
        for ref_type, ref_id in refs:
            if ref_type == "dataset" and ref_id in hdca_parents:
                result.add(("collection", hdca_parents[ref_id]))
            else:
                result.add((ref_type, ref_id))
        return result

    def _collection_element_edges(self, hdca_ids: set[int]) -> set[tuple[int, int]]:
        """Walk each HDCA's collection tree and return ``(hda_id, hdca_id)``
        pairs for every visible leaf HDA element. Hidden elements are
        suppressed, mirroring ``_remove_hidden_elements``. Nested collections
        are traversed transparently: intermediate ``child_collection``s do not
        get HDCA nodes, so leaf HDAs wire directly to the top-level HDCA they
        belong to."""
        if not hdca_ids:
            return set()

        root_stmt = select(
            HistoryDatasetCollectionAssociation.id,
            HistoryDatasetCollectionAssociation.collection_id,
        ).where(HistoryDatasetCollectionAssociation.id.in_(hdca_ids))
        roots = {row.collection_id: row.id for row in self.sa_session.execute(root_stmt)}
        if not roots:
            return set()

        edges: set[tuple[int, int]] = set()
        dc_to_root: dict[int, int] = dict(roots)
        frontier: set[int] = set(roots.keys())
        seen: set[int] = set()
        while frontier:
            stmt = select(
                DatasetCollectionElement.dataset_collection_id,
                DatasetCollectionElement.hda_id,
                DatasetCollectionElement.child_collection_id,
            ).where(DatasetCollectionElement.dataset_collection_id.in_(frontier))
            next_frontier: set[int] = set()
            for row in self.sa_session.execute(stmt):
                root_hdca = dc_to_root[row.dataset_collection_id]
                if row.hda_id is not None:
                    edges.add((row.hda_id, root_hdca))
                elif row.child_collection_id is not None and row.child_collection_id not in seen:
                    dc_to_root[row.child_collection_id] = root_hdca
                    next_frontier.add(row.child_collection_id)
            seen |= frontier
            frontier = next_frontier - seen

        # Suppress hidden elements: a tool-produced collection's internal
        # element HDAs are hidden and must not surface as dataset nodes —
        # mirrors ``_remove_hidden_elements``, without which the closure
        # would re-add them.
        if not edges:
            return edges
        leaf_hda_ids = {hda_id for hda_id, _ in edges}
        visible_stmt = select(HistoryDatasetAssociation.id).where(
            HistoryDatasetAssociation.id.in_(leaf_hda_ids),
            HistoryDatasetAssociation.visible == True,  # noqa: E712
        )
        visible_ids = {row.id for row in self.sa_session.execute(visible_stmt)}
        return {(hda_id, hdca_id) for hda_id, hdca_id in edges if hda_id in visible_ids}

    def _emit_input_edges(
        self,
        producer_ref: NodeRef,
        payload: dict,
        dataset_ids: set[int],
        collection_ids: set[int],
        edges: list[GraphEdge],
        closure_dataset_ids: set[int],
        closure_collection_ids: set[int],
    ) -> None:
        """Emit ``*_input`` edges from a resolved request payload into the
        given producer node, collecting any out-of-scope refs as closure.
        Source-neutral: the producer may be a ToolRequest or a
        WorkflowInvocationStep; only its already-encoded node ref matters."""
        for ref_type, ref_id in self._extract_inputs(payload):
            etype = "dataset_input" if ref_type == "dataset" else "collection_input"
            edges.append(GraphEdge(source=self._ref(ref_type, ref_id), target=producer_ref, type=etype))
            if ref_type == "dataset" and ref_id not in dataset_ids:
                closure_dataset_ids.add(ref_id)
            elif ref_type == "collection" and ref_id not in collection_ids:
                closure_collection_ids.add(ref_id)

    # ── Node construction ──

    def _dataset_nodes(self, db_ids: set[int]) -> list[GraphNode]:
        if not db_ids:
            return []
        stmt = (
            select(
                HistoryDatasetAssociation.id,
                HistoryDatasetAssociation.name,
                HistoryDatasetAssociation.hid,
                HistoryDatasetAssociation._state,
                Dataset.state.label("dataset_state"),
                HistoryDatasetAssociation.extension,
                HistoryDatasetAssociation.deleted,
                HistoryDatasetAssociation.visible,
            )
            .join(Dataset, HistoryDatasetAssociation.dataset_id == Dataset.id)
            .where(HistoryDatasetAssociation.id.in_(db_ids))
        )
        return [
            self._node(
                "dataset",
                row.id,
                name=row.name,
                hid=row.hid,
                state=row._state if row._state else row.dataset_state,
                extension=row.extension,
                deleted=row.deleted,
                visible=row.visible,
            )
            for row in self.sa_session.execute(stmt)
        ]

    def _collection_nodes(self, db_ids: set[int]) -> list[GraphNode]:
        if not db_ids:
            return []
        stmt = (
            select(
                HistoryDatasetCollectionAssociation.id,
                HistoryDatasetCollectionAssociation.name,
                HistoryDatasetCollectionAssociation.hid,
                HistoryDatasetCollectionAssociation.deleted,
                HistoryDatasetCollectionAssociation.visible,
                DatasetCollection.collection_type,
                DatasetCollection.populated_state,
            )
            .join(DatasetCollection, HistoryDatasetCollectionAssociation.collection_id == DatasetCollection.id)
            .where(HistoryDatasetCollectionAssociation.id.in_(db_ids))
        )
        return [
            self._node(
                "collection",
                row.id,
                name=row.name,
                hid=row.hid,
                state=row.populated_state,
                collection_type=row.collection_type,
                deleted=row.deleted,
                visible=row.visible,
            )
            for row in self.sa_session.execute(stmt)
        ]

    def _producer_nodes(self, producer_meta: dict[tuple[str, int], Optional[str]]) -> list[GraphNode]:
        """Producer nodes for both structured-request sources. Wire ``src``
        is "tool_execution" uniformly; the cipher kind embedded in the id
        distinguishes ToolExecutionState-backed producers from historical
        ToolRequest ones so same-pk rows in the two tables never collide.
        """
        return [
            GraphNode(
                src="tool_execution",
                id=self._producer_ref(source, source_id).id,
                tool_id=tool_id,
            )
            for (source, source_id), tool_id in producer_meta.items()
        ]

    def _resolve_tool_names(self, nodes: list[GraphNode]) -> None:
        toolbox = self.toolbox
        if toolbox is None:
            return
        tool_ids = {n.tool_id for n in nodes if n.src == "tool_execution" and n.tool_id}
        name_map: dict[str, str] = {}
        for tool_id in tool_ids:
            try:
                tool = toolbox.get_tool(tool_id)
                if tool and tool.name:
                    name_map[tool_id] = tool.name
            except MessageException:
                pass
        for node in nodes:
            if node.src == "tool_execution" and node.tool_id and node.tool_id in name_map:
                node.tool_name = name_map[node.tool_id]

    # ── Seed subgraph filter (in-memory only) ──

    def _seed_filter(
        self, seed: NodeRef, nodes: list[GraphNode], edges: list[GraphEdge]
    ) -> tuple[list[GraphNode], list[GraphEdge]]:
        node_ids = {n.ref for n in nodes}
        if seed not in node_ids:
            raise RequestParameterInvalidException(f"Seed {seed.src}:{seed.id} not found in graph.")

        out_map: dict[NodeRef, set[NodeRef]] = {}
        in_map: dict[NodeRef, set[NodeRef]] = {}
        for e in edges:
            out_map.setdefault(e.source, set()).add(e.target)
            in_map.setdefault(e.target, set()).add(e.source)

        reachable: set[NodeRef] = {seed}
        frontier = {seed}
        for _ in range(self.depth):
            nxt: set[NodeRef] = set()
            for nid in frontier:
                if self.direction in ("forward", "both"):
                    nxt |= out_map.get(nid, set()) - reachable
                if self.direction in ("backward", "both"):
                    nxt |= in_map.get(nid, set()) - reachable
            if not nxt:
                break
            reachable |= nxt
            frontier = nxt
        return (
            [n for n in nodes if n.ref in reachable],
            [e for e in edges if e.source in reachable and e.target in reachable],
        )

    # ── Sort ──

    def _sort(self, nodes: list[GraphNode], edges: list[GraphEdge]) -> tuple[list[GraphNode], list[GraphEdge]]:
        fallback = (99, 0)
        nodes.sort(key=lambda n: self._sort_keys.get(n.ref, fallback))
        edges.sort(
            key=lambda e: (
                self._sort_keys.get(e.source, fallback),
                self._sort_keys.get(e.target, fallback),
                EDGE_TYPE_RANK.get(e.type, 99),
            )
        )
        return nodes, edges

    # ── Utilities ──

    def _ref(self, node_type: str, db_id: int) -> NodeRef:
        ref = NodeRef(src=NODE_SRC[node_type], id=self.security.encode_id(db_id))
        self._sort_keys[ref] = (TYPE_RANK[node_type], db_id)
        return ref

    def _producer_ref(self, source: str, source_id: int) -> NodeRef:
        """Encode a producer node for either structured-request source.

        Wire ``src`` is "tool_execution" uniformly. The cipher kind differs
        per source so a ToolExecutionState and a historical ToolRequest
        with the same integer pk never encode to the same node ref.
        """
        if source == "tool_execution_state":
            encoded = self.security.encode_id(source_id, kind=TOOL_EXECUTION_STATE_ENCODE_KIND)
        else:
            encoded = self.security.encode_id(source_id)
        ref = NodeRef(src="tool_execution", id=encoded)
        self._sort_keys[ref] = (TYPE_RANK["tool_execution"], source_id)
        return ref

    def _node(self, node_type: str, db_id: int, **fields) -> GraphNode:
        ref = self._ref(node_type, db_id)
        return GraphNode(src=ref.src, id=ref.id, **fields)
