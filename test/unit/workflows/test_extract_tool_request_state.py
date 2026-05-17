from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from galaxy import exceptions
from galaxy import model
from galaxy.tool_util.parameters import RequestInternalToWorkflowStateError
from galaxy.workflow import extract


def test_step_inputs_by_id_calls_legacy_when_tool_request_absent(monkeypatch):
    legacy_result = ({"parameter": "value"}, [])
    legacy = Mock(return_value=legacy_result)
    monkeypatch.setattr(extract, "_legacy_step_inputs_by_id", legacy)
    job = SimpleNamespace(id=42, history_id=7, tool_request=None)
    trans = SimpleNamespace(app=SimpleNamespace(execution_timer_factory=None))

    result = extract.step_inputs_by_id(trans, job)

    assert result == legacy_result
    legacy.assert_called_once_with(trans, job)


def test_step_inputs_by_id_fallback_disabled_raises_when_tool_request_absent(monkeypatch):
    legacy = Mock()
    monkeypatch.setattr(extract, "_legacy_step_inputs_by_id", legacy)
    job = SimpleNamespace(id=42, tool_request=None)
    trans = SimpleNamespace()

    with pytest.raises(exceptions.RequestParameterInvalidException, match="legacy workflow extraction state fallback"):
        extract.step_inputs_by_id(trans, job, fallback_to_legacy_state=False)

    legacy.assert_not_called()


def test_step_inputs_by_id_structured_error_does_not_fallback(monkeypatch):
    legacy = Mock()
    tool_request = object()

    def fail_structured(trans, job, tool_request):
        raise RequestInternalToWorkflowStateError("broken structured state")

    monkeypatch.setattr(extract, "_legacy_step_inputs_by_id", legacy)
    monkeypatch.setattr(extract, "_structured_step_inputs_by_id", fail_structured)
    job = SimpleNamespace(id=42, tool_request=tool_request)
    trans = SimpleNamespace()

    with pytest.raises(RequestInternalToWorkflowStateError, match="broken structured state"):
        extract.step_inputs_by_id(trans, job, fallback_to_legacy_state=True)

    legacy.assert_not_called()


def test_icj_ambiguous_tool_request_returns_none_and_logs(caplog):
    icj = model.ImplicitCollectionJobs()
    icj.id = 123
    icj.get_job_attributes = Mock(
        return_value=[
            SimpleNamespace(tool_request_id=1),
            SimpleNamespace(tool_request_id=2),
            SimpleNamespace(tool_request_id=2),
        ]
    )

    assert icj.has_ambiguous_tool_request
    assert icj.tool_request is None
    assert "multiple tool_request_id values" in caplog.text


def test_url_input_steps_for_request_annotates_original_url_request():
    tool_request = model.ToolRequest()
    tool_request.request = {
        "input1": {
            "src": "url",
            "url": "https://example.org/data.txt",
            "ext": "txt",
        }
    }
    step_labels: set[str] = set()

    url_steps = extract._url_input_steps_for_request(SimpleNamespace(user=None), tool_request, step_labels)

    assert len(url_steps) == 1
    input_name, step = url_steps[0]
    assert input_name == "input1"
    assert step.type == "data_input"
    assert step.tool_inputs == {"name": "input1"}
    assert step.annotations[0].annotation == '{"ext": "txt", "src": "url", "url": "https://example.org/data.txt"}'
