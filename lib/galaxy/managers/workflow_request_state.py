"""Resolve the structured request_internal payload backing an execution.

A tool execution's validated request_internal state lives on a
``ToolExecutionState`` row. This module is the single seam mapping an
execution unit (``Job`` / ``ImplicitCollectionJobs`` / ``ToolRequest``)
to that payload, so workflow extraction and the History Graph share
one resolution path. ``resolve_structured_request`` always returns a
``ResolvedStructuredRequest`` whose ``state`` field discriminates the
failure modes (no TES row, validation-skipped, validation-failed) so
consumers can react with state-specific diagnostics rather than
collapsing every "no payload" case into a single ``None``.
"""

import logging
from enum import Enum
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


class ResolutionState(str, Enum):
    """Discriminator on the resolver outcome. The first three values
    mirror ``ToolExecutionStateValidity``; ``MISSING`` covers the no-TES
    case (pre-structured-capture historical executions).
    """

    VALIDATED = ToolExecutionStateValidity.VALIDATED.value
    NOT_VALIDATED = ToolExecutionStateValidity.NOT_VALIDATED.value
    VALIDATION_FAILED = ToolExecutionStateValidity.VALIDATION_FAILED.value
    MISSING = "missing"


class ResolvedStructuredRequest(NamedTuple):
    """Discriminated resolver outcome.

    ``state`` is always set. ``source_id`` is the ``ToolExecutionState.id``
    when ``state != MISSING``; ``payload`` is the validated
    ``request_internal`` dict only when ``state == VALIDATED``;
    ``tool_execution_state`` is the producing TES row whenever
    ``state != MISSING`` so consumers can route it straight to
    :func:`galaxy.managers.tool_execution.tool_for_execution` without a
    second lookup. The TES field is a live SQLA row, valid only for the
    lifetime of the session that produced it. Callers that only want the
    validated payload can use :func:`resolve_structured_request_payload`
    for parity with the prior ``Optional[dict]`` shape.
    """

    state: ResolutionState
    source_id: Optional[int] = None
    payload: Optional[dict] = None
    tool_execution_state: Optional[ToolExecutionState] = None


def _tes_from_job(job: Optional[Job]) -> Optional[ToolExecutionState]:
    """Walk a Job to its canonical TES via the ICJ-supersedes rule.

    Order of precedence:
    - Job under an ICJ: read through the ICJ (the canonical anchor for
      mapped executions; the per-Job FK is intentionally NULL).
    - Job with a direct FK: read it (tool-request-sourced standalone jobs).
    - Otherwise walk to the workflow_invocation_step's TES: a workflow tool
      step always mints a WIS-side TES (per workflow/modules.py), but
      execute.py only propagates the link to the Job when the capture
      validated. Reading through the WIS recovers the source TES for
      NOT_VALIDATED / VALIDATION_FAILED workflow tool executions so they
      stay orderable by TES.id rather than dropping to legacy Job.id space.
    """
    if job is None:
        return None
    icj_assoc = job.implicit_collection_jobs_association
    if icj_assoc is not None and icj_assoc.implicit_collection_jobs is not None:
        return icj_assoc.implicit_collection_jobs.tool_execution_state
    if job.tool_execution_state is not None:
        return job.tool_execution_state
    wis = job.workflow_invocation_step
    if wis is not None:
        return wis.tool_execution_state
    return None


def _tes_from_icj(icj: ImplicitCollectionJobs) -> Optional[ToolExecutionState]:
    return icj.tool_execution_state


def _tes_from_tool_request(tool_request: ToolRequest) -> Optional[ToolExecutionState]:
    return tool_request.tool_execution_state


def _resolved_from_tes(tes: Optional[ToolExecutionState]) -> ResolvedStructuredRequest:
    if tes is None:
        return ResolvedStructuredRequest(state=ResolutionState.MISSING)
    raw_state = tes.state
    try:
        state = ResolutionState(raw_state)
    except ValueError:
        log.warning("ToolExecutionState %s has unrecognized state %r; treating as VALIDATION_FAILED", tes.id, raw_state)
        state = ResolutionState.VALIDATION_FAILED
    if state != ResolutionState.VALIDATED:
        return ResolvedStructuredRequest(state=state, source_id=tes.id, tool_execution_state=tes)
    payload = tes.request
    # Data-model invariant: TES.state == 'validated' implies a dict payload.
    # Crash here rather than silently degrade: a non-dict payload at this
    # point indicates a write-side bug that needs investigation, not a
    # case the consumer should paper over.
    assert isinstance(
        payload, dict
    ), f"ToolExecutionState {tes.id} state is 'validated' but payload is {type(payload).__name__}"
    return ResolvedStructuredRequest(state=state, source_id=tes.id, payload=payload, tool_execution_state=tes)


def resolve_structured_request(
    job: Optional[Job] = None,
    icj: Optional[ImplicitCollectionJobs] = None,
    tool_request: Optional[ToolRequest] = None,
) -> ResolvedStructuredRequest:
    """Resolve the structured request_internal payload for an execution unit.

    For a Job under an ICJ, the ICJ holds the canonical TES link; for a
    standalone Job, the Job's direct TES link is used. The returned
    ``ResolvedStructuredRequest`` always carries a ``state``; only
    ``state == VALIDATED`` has a populated ``payload``.
    """
    if icj is not None:
        tes = _tes_from_icj(icj)
    elif tool_request is not None:
        tes = _tes_from_tool_request(tool_request)
    else:
        tes = _tes_from_job(job)
    resolved = _resolved_from_tes(tes)
    assert (resolved.tool_execution_state is None) == (resolved.state == ResolutionState.MISSING)
    return resolved


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
    return resolved.payload if resolved.state == ResolutionState.VALIDATED else None


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
