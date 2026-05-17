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


def _trans(tool_requests_by_id):
    sa_session = SimpleNamespace(get=lambda _model, id_: tool_requests_by_id.get(id_))
    history_manager = SimpleNamespace(error_unless_accessible=lambda _history, _user: None)
    app = SimpleNamespace(history_manager=history_manager, dataset_collection_manager=Mock())
    return SimpleNamespace(sa_session=sa_session, app=app, user=SimpleNamespace())


def _tool_request(state):
    return SimpleNamespace(state=state, history=SimpleNamespace())


def _validate(tool_requests_by_id, **payload_kwargs):
    # model_construct skips DecodedDatabaseIdField decoding (encoded-id +
    # Security helper) -- irrelevant to the DB-level decision under test;
    # missing list fields fall back to their default_factory ([]).
    payload = WorkflowExtractionByIdsPayload.model_construct(**payload_kwargs)
    _service()._validate_extract_by_ids_payload(_trans(tool_requests_by_id), payload)


def test_lone_single_new_tool_request_accepted():
    # NEW_STATE_POLICY hybrid: a lone single 'new' request is a valid
    # single-step extraction (no outputs to wire anyway).
    _validate({1: _tool_request("new")}, tool_request_ids=[1])


def test_lone_single_submitted_tool_request_accepted():
    _validate({1: _tool_request("submitted")}, tool_request_ids=[1])


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


def test_submitted_tool_requests_multi_accepted():
    # Control: the guard must not over-reject -- multiple 'submitted'
    # requests remain valid (step 1's proven path).
    _validate(
        {1: _tool_request("submitted"), 2: _tool_request("submitted")},
        tool_request_ids=[1, 2],
    )
