"""Resolve the structured request_internal payload backing an execution.

A tool execution's validated request_internal state lives on a
``ToolExecutionState`` row reached uniformly through
``Job.tool_execution_state`` (the EXEC_STATE schema). For historical
pre-EXEC_STATE tool-request rows the payload still lives on
``ToolRequest.request`` and is consulted as a transitional fallback.
This module is the single source-neutral seam mapping an execution unit
(``Job`` / ``ImplicitCollectionJobs``) to that payload, so workflow
extraction and the History Graph share one resolution path. Returning a
plain dict rather than a backing object keeps every consumer
source-neutral.
"""

import json
import logging
from typing import (
    Literal,
    NamedTuple,
    Optional,
)

from galaxy.model import (
    ImplicitCollectionJobs,
    Job,
    required_object_session,
    ToolExecutionState,
    ToolRequest,
)
from galaxy.schema.schema import ToolExecutionStateValidity
from galaxy.tool_util.parameters import RequestInternalToWorkflowStateError

log = logging.getLogger(__name__)

VALIDATED_REQUEST_STATE = ToolExecutionStateValidity.VALIDATED.value

StructuredRequestSource = Literal["tool_execution_state", "tool_request"]


class ResolvedStructuredRequest(NamedTuple):
    """A resolved structured request_internal payload plus the identity of
    the backing store it came from.

    ``source_id`` is the ``ToolExecutionState.id`` for the unified
    EXEC_STATE source, or the ``ToolRequest.id`` for the transitional
    historical fallback. Consumers that only need the payload use
    :func:`resolve_structured_request_payload`; consumers that also need a
    stable per-producer identity (e.g. the History Graph producer node)
    use :func:`resolve_structured_request`. The two source id-spaces are
    distinct tables and may collide as integers, so a consumer keying on
    ``source_id`` must also key on ``source``.
    """

    source: StructuredRequestSource
    source_id: int
    payload: dict


def unambiguous_id(ids: set[int]) -> Optional[int]:
    """Exactly one id -> that id; none or ambiguous (>1) -> None.

    The shared trichotomy rule: a consumer that resolves >1 (or 0)
    distinct producing ids across an ICJ's constituent jobs has no
    single structured request and degrades to None.
    """
    return next(iter(ids)) if len(ids) == 1 else None


def _tool_request_payload(tool_request: ToolRequest) -> dict:
    payload = json.loads(tool_request.request) if isinstance(tool_request.request, str) else tool_request.request
    if not isinstance(payload, dict):
        raise RequestInternalToWorkflowStateError(f"ToolRequest {tool_request.id} has malformed request payload")
    return payload


def tool_request_payload(tool_request: ToolRequest) -> dict:
    """Return the validated request_internal payload stored on a ToolRequest."""
    return _tool_request_payload(tool_request)


def _job_tool_execution_state(job: Optional[Job]) -> tuple[Optional[ToolExecutionState], bool]:
    """``(tes, has_link)`` for a Job: ``has_link`` is True iff
    ``Job.tool_execution_state_id IS NOT NULL``. The caller uses
    ``has_link`` to decide whether to fall back to the historical
    ``ToolRequest`` payload - any TES link shadows the fallback, even
    when the TES is non-validated."""
    if job is None:
        return None, False
    tes = job.tool_execution_state
    return tes, tes is not None


def _icj_tool_execution_state(icj: ImplicitCollectionJobs) -> tuple[Optional[ToolExecutionState], bool]:
    """``(tes, has_link)`` for an ICJ: distinct TES ids across constituent
    jobs (``get_job_attributes(["tool_execution_state_id"])``).

    - Exactly one id -> unambiguous, return ``(TES, True)``.
    - Zero ids -> no link, return ``(None, False)``; caller may fall back.
    - >1 ids -> ambiguous (the trichotomy rule); return ``(None, True)``
      so the caller treats it like the Job-path "TES present but
      indeterminate" case and shadows the historical fallback rather
      than risking a stale ``ToolRequest`` payload for an ICJ whose
      jobs disagree on producer.

    Under the normal mint pipeline every job in an ICJ shares the same
    TES (linked in lockstep on validated capture), so ambiguous is a
    code-defect signal worth surfacing as "no usable payload" rather
    than silently degrading.
    """
    session = required_object_session(icj)
    tes_ids = {
        row.tool_execution_state_id
        for row in icj.get_job_attributes(["tool_execution_state_id"])
        if row.tool_execution_state_id
    }
    if not tes_ids:
        return None, False
    tes_id = unambiguous_id(tes_ids)
    if tes_id is None:
        return None, True
    return session.get(ToolExecutionState, tes_id), True


def resolve_structured_request(
    job: Optional[Job] = None,
    icj: Optional[ImplicitCollectionJobs] = None,
) -> Optional[ResolvedStructuredRequest]:
    """Resolve the structured request_internal payload + its backing-store
    identity for an execution unit.

    Uniform EXEC_STATE walk first: ``Job.tool_execution_state`` (or, for
    an ICJ, the unambiguous TES across its jobs). Any TES link shadows
    the historical fallback - a TES whose state is not ``validated``, or
    an ICJ whose jobs disagree on producer, returns None rather than
    risking a stale ToolRequest payload.

    Transitional historical fallback: when NO TES link exists at all,
    walk ``Job.tool_request`` (or ``icj.structured_request``) -
    pre-EXEC_STATE tool-request rows still carry the authoritative
    payload on ``ToolRequest.request``. Workflow-produced historical
    rows have neither and resolve to None.
    """
    tes, has_tes_link = _icj_tool_execution_state(icj) if icj is not None else _job_tool_execution_state(job)
    if has_tes_link:
        if tes is None or tes.state != VALIDATED_REQUEST_STATE:
            return None
        payload = tes.request
        if not isinstance(payload, dict):
            return None
        return ResolvedStructuredRequest("tool_execution_state", tes.id, payload)

    tool_request = icj.structured_request if icj is not None else (job.tool_request if job is not None else None)
    if tool_request is not None:
        return ResolvedStructuredRequest("tool_request", tool_request.id, _tool_request_payload(tool_request))
    return None


def resolve_structured_request_payload(
    job: Optional[Job] = None,
    icj: Optional[ImplicitCollectionJobs] = None,
) -> Optional[dict]:
    """Resolve just the structured request_internal payload for an execution
    unit (see :func:`resolve_structured_request` for the source-identity
    variant). Returns None when no unambiguous validated payload is
    reachable; the caller then degrades to the legacy state walk.
    """
    resolved = resolve_structured_request(job=job, icj=icj)
    return resolved.payload if resolved is not None else None
