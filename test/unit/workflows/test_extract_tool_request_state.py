from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from galaxy import exceptions
from galaxy import model
from galaxy.tool_util.parameters import RequestInternalToWorkflowStateError
from galaxy.tool_util.parameters.request import RequestInputRef
from galaxy.workflow import extract


def test_step_inputs_by_id_fallback_disabled_raises_without_structured_payload():
    # No structured payload + fallback disabled => hard error, never legacy.
    job = SimpleNamespace(id=42)
    trans = SimpleNamespace()

    with pytest.raises(exceptions.RequestParameterInvalidException, match="legacy workflow extraction state fallback"):
        extract.step_inputs_by_id(trans, job, fallback_to_legacy_state=False)


def test_step_inputs_by_id_structured_error_does_not_fallback(monkeypatch):
    # Boundedness invariant: a structured-conversion failure propagates and
    # MUST NOT silently degrade to the legacy path.
    legacy = Mock()

    def fail_structured(trans, job, request_payload):
        raise RequestInternalToWorkflowStateError("broken structured state")

    monkeypatch.setattr(extract, "_legacy_step_inputs_by_id", legacy)
    monkeypatch.setattr(extract, "_structured_step_inputs_by_id", fail_structured)
    job = SimpleNamespace(id=42)
    trans = SimpleNamespace()

    with pytest.raises(RequestInternalToWorkflowStateError, match="broken structured state"):
        extract.step_inputs_by_id(
            trans, job, request_payload={"parameter": {"src": "hda", "id": 1}}, fallback_to_legacy_state=True
        )

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


def test_structured_request_payload_seam():
    # The single source-neutral seam: ToolRequest -> request_internal dict,
    # or None when the execution has no unambiguous tool request.
    tool_request = model.ToolRequest()
    tool_request.request = {"parameter": {"src": "hda", "id": 1}}

    assert extract._structured_request_payload(job=SimpleNamespace(tool_request=tool_request)) == {
        "parameter": {"src": "hda", "id": 1}
    }
    assert extract._structured_request_payload(job=SimpleNamespace(tool_request=None)) is None
    assert extract._structured_request_payload() is None


def test_association_for_request_ref_dce_resolves_to_leaf_hda(monkeypatch):
    # dce content_type dereferences to the element's leaf HDA.
    monkeypatch.setattr(extract, "_original_hda", lambda hda: hda)
    hda = model.HistoryDatasetAssociation(id=77, create_dataset=False)
    dce = SimpleNamespace(hda=hda)
    trans = SimpleNamespace(sa_session=SimpleNamespace(get=lambda model_cls, id_: dce))

    ref = RequestInputRef("dataset_collection_element", 9, "input1", "dce")
    assert extract._association_for_request_ref(trans, ref) == ("dataset", 77)


def test_association_for_request_ref_unresolved_logs_and_returns_none(caplog):
    # An unresolvable ref must warn and return None (no spurious connection).
    trans = SimpleNamespace(sa_session=SimpleNamespace(get=lambda model_cls, id_: None))

    ref = RequestInputRef("dataset", 404, "input1", "hda")
    assert extract._association_for_request_ref(trans, ref) is None
    assert "could not resolve request input ref" in caplog.text


def test_url_input_steps_for_request_annotates_original_url_request():
    request_payload = {
        "input1": {
            "src": "url",
            "url": "https://example.org/data.txt",
            "ext": "txt",
        }
    }
    step_labels: set[str] = set()

    url_steps = extract._url_input_steps_for_request(SimpleNamespace(user=None), request_payload, step_labels)

    assert len(url_steps) == 1
    input_name, step = url_steps[0]
    assert input_name == "input1"
    assert step.type == "data_input"
    assert step.tool_inputs == {"name": "input1"}
    assert step.annotations[0].annotation == '{"ext": "txt", "src": "url", "url": "https://example.org/data.txt"}'
