from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from galaxy import exceptions
from galaxy.schema.workflows import WorkflowExtractionByIdsPayload
from galaxy.webapps.galaxy.services.workflows import WorkflowsService


def _service() -> WorkflowsService:
    # Bypass __init__ -- a tool_request-only payload never touches the
    # injected managers; the validator only uses trans/sa_session.
    return WorkflowsService.__new__(WorkflowsService)


def _trans(tool_requests_by_id=None, icjs_by_id=None):
    tool_requests_by_id = tool_requests_by_id or {}
    icjs_by_id = icjs_by_id or {}

    def _get(model_class, id_):
        if model_class.__name__ == "ImplicitCollectionJobs":
            return icjs_by_id.get(id_)
        return tool_requests_by_id.get(id_)

    sa_session = SimpleNamespace(get=_get)
    history_manager = SimpleNamespace(error_unless_accessible=lambda _history, _user: None)
    app = SimpleNamespace(history_manager=history_manager, dataset_collection_manager=Mock())
    return SimpleNamespace(sa_session=sa_session, app=app, user=SimpleNamespace())


_next_tool_request_id = 1000


def _tool_request(state):
    global _next_tool_request_id
    _next_tool_request_id += 1
    return SimpleNamespace(id=_next_tool_request_id, state=state, history=SimpleNamespace())


def _icj(jobs_present: bool, tool_request_for_hdca=None):
    """Build a minimal ImplicitCollectionJobs mock.

    Under unified TES.id ordering both ``jobs_present`` variants and the
    jobless-TR-backed variant produce comparable sort keys; the validator
    no longer rejects mixed shapes. A TR-backed ICJ is wired via its
    ``tool_execution_state.tool_request`` (the canonical post-TRICA path).
    """
    output_hdca = SimpleNamespace(id=0)
    tes = SimpleNamespace(tool_request=tool_request_for_hdca) if tool_request_for_hdca is not None else None
    return SimpleNamespace(
        populated_state="ok",
        output_dataset_collection_instances=[output_hdca],
        jobs=[SimpleNamespace()] if jobs_present else [],
        tool_execution_state=tes,
    )


def _validate(tool_requests_by_id=None, icjs_by_id=None, **payload_kwargs):
    # model_construct skips DecodedDatabaseIdField decoding (encoded-id +
    # Security helper) -- irrelevant to the DB-level decision under test;
    # missing list fields fall back to their default_factory ([]).
    payload = WorkflowExtractionByIdsPayload.model_construct(**payload_kwargs)
    _service()._validate_extract_by_ids_payload(_trans(tool_requests_by_id, icjs_by_id), payload)


def test_lone_single_new_tool_request_accepted():
    # NEW_STATE_POLICY hybrid: a lone single 'new' request is a valid
    # single-step extraction (no outputs to wire anyway).
    _validate({1: _tool_request("new")}, tool_request_ids=[1])


def test_new_tool_request_among_multiple_rejected():
    # >1 request with a 'new' member would be a silently un-wireable
    # producer -- reject, do not emit a partial workflow.
    with pytest.raises(exceptions.RequestParameterInvalidException, match="not yet materialized"):
        _validate(
            {1: _tool_request("new"), 2: _tool_request("submitted")},
            tool_request_ids=[1, 2],
        )


def test_new_tool_request_with_other_selection_rejected():
    # Not lone (hdca_ids also selected) => the 'new' step cannot be a
    # standalone single-node workflow.
    with pytest.raises(exceptions.RequestParameterInvalidException, match="not yet materialized"):
        _validate({1: _tool_request("new")}, tool_request_ids=[1], hdca_ids=[99])


def test_icj_mix_job_keyed_and_tool_request_keyed_accepted():
    # Previously rejected: a Job-keyed ICJ and a jobless tool-request-backed
    # ICJ used different id spaces (Job.id vs ToolRequest.id). Under unified
    # TES.id ordering both items resolve their sort key from the shared
    # ToolExecutionState seam, so the mix-guard is gone.
    tr = _tool_request("submitted")
    icjs = {
        10: _icj(jobs_present=True),  # was Job-keyed
        20: _icj(jobs_present=False, tool_request_for_hdca=tr),  # was ToolRequest-keyed
    }
    _validate(icjs_by_id=icjs, implicit_collection_jobs_ids=[10, 20])


def test_icj_two_job_keyed_accepted():
    # Control: classic + classic (or grey-tool-request + classic) all keyed
    # via the resolver -- still accepted.
    icjs = {1: _icj(jobs_present=True), 2: _icj(jobs_present=True)}
    _validate(icjs_by_id=icjs, implicit_collection_jobs_ids=[1, 2])


def test_tool_request_ids_mixed_with_job_ids_accepted():
    # Previously rejected: a single payload mixing tool_request_ids with
    # job_ids/implicit_collection_jobs_ids crossed the TR.id / Job.id id
    # spaces. Under unified TES.id ordering both keys map to TES.id at
    # work-item construction, so the mix is accepted at validation time.
    _validate(
        {1: _tool_request("submitted")},
        tool_request_ids=[1],
        job_ids=[],  # the validator only checks the mix shape; the loop below is empty
    )


def test_tool_request_ids_mixed_with_icj_ids_accepted():
    # Same rationale as above, exercising the implicit_collection_jobs_ids
    # companion list.
    tr = _tool_request("submitted")
    icjs = {10: _icj(jobs_present=True)}
    _validate(
        {1: tr},
        icjs_by_id=icjs,
        tool_request_ids=[1],
        implicit_collection_jobs_ids=[10],
    )
