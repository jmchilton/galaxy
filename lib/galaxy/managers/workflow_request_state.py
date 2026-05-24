"""Resolve the structured request_internal payload backing an execution.

A tool execution's validated request_internal state lives on a
``ToolExecutionState`` row. This module is the single seam mapping an
execution unit (``Job`` / ``ImplicitCollectionJobs`` / ``ToolRequest``)
to that payload, so workflow extraction and the History Graph share
one resolution path. Returning a plain dict rather than a backing
object keeps every consumer source-neutral.
"""

import logging
from typing import (
    NamedTuple,
    Optional,
)

from galaxy.model import (
    ImplicitCollectionJobs,
    Job,
    ToolExecutionState,
    ToolRequest,
)
from galaxy.schema.schema import ToolExecutionStateValidity
from galaxy.tool_util.parameters import RequestInternalToWorkflowStateError

log = logging.getLogger(__name__)

VALIDATED_REQUEST_STATE = ToolExecutionStateValidity.VALIDATED.value


class ResolvedStructuredRequest(NamedTuple):
    """A resolved structured request_internal payload plus the
    ``ToolExecutionState.id`` it came from. Consumers that only need the
    payload use :func:`resolve_structured_request_payload`; consumers
    that also need a stable per-producer identity (e.g. the History
    Graph producer node) use :func:`resolve_structured_request`.
    """

    source_id: int
    payload: dict


def _tes_from_job(job: Optional[Job]) -> Optional[ToolExecutionState]:
    if job is None:
        return None
    icj_assoc = job.implicit_collection_jobs_association
    if icj_assoc is not None and icj_assoc.implicit_collection_jobs is not None:
        return icj_assoc.implicit_collection_jobs.tool_execution_state
    return job.tool_execution_state


def _tes_from_icj(icj: ImplicitCollectionJobs) -> Optional[ToolExecutionState]:
    return icj.tool_execution_state


def _tes_from_tool_request(tool_request: ToolRequest) -> Optional[ToolExecutionState]:
    return tool_request.tool_execution_state


def _resolved_from_tes(tes: Optional[ToolExecutionState]) -> Optional[ResolvedStructuredRequest]:
    if tes is None or tes.state != VALIDATED_REQUEST_STATE:
        return None
    payload = tes.request
    if not isinstance(payload, dict):
        return None
    return ResolvedStructuredRequest(tes.id, payload)


def resolve_structured_request(
    job: Optional[Job] = None,
    icj: Optional[ImplicitCollectionJobs] = None,
    tool_request: Optional[ToolRequest] = None,
) -> Optional[ResolvedStructuredRequest]:
    """Resolve the structured request_internal payload + the
    ToolExecutionState.id it came from for an execution unit.

    For a Job under an ICJ, the ICJ holds the canonical TES link; for a
    standalone Job, the Job's direct TES link is used. A non-validated
    TES, missing TES link, or malformed payload returns None.
    """
    if icj is not None:
        tes = _tes_from_icj(icj)
    elif tool_request is not None:
        tes = _tes_from_tool_request(tool_request)
    else:
        tes = _tes_from_job(job)
    return _resolved_from_tes(tes)


def resolve_structured_request_payload(
    job: Optional[Job] = None,
    icj: Optional[ImplicitCollectionJobs] = None,
    tool_request: Optional[ToolRequest] = None,
) -> Optional[dict]:
    """Resolve just the structured request_internal payload for an
    execution unit. Returns None when no validated payload is reachable;
    the caller then degrades to the legacy state walk.
    """
    resolved = resolve_structured_request(job=job, icj=icj, tool_request=tool_request)
    return resolved.payload if resolved is not None else None


def tool_request_payload(tool_request: ToolRequest) -> dict:
    """Return the validated request_internal payload for a ToolRequest.
    Reads through ``tool_request.tool_execution_state``; raises
    ``RequestInternalToWorkflowStateError`` if the TES is missing or
    malformed.
    """
    tes = tool_request.tool_execution_state
    if tes is None:
        raise RequestInternalToWorkflowStateError(f"ToolRequest {tool_request.id} has no tool_execution_state")
    payload = tes.request
    if not isinstance(payload, dict):
        raise RequestInternalToWorkflowStateError(f"ToolRequest {tool_request.id} has malformed request payload")
    return payload
