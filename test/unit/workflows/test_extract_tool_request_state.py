from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from galaxy import (
    exceptions,
    model,
)
from galaxy.app_unittest_utils.tools_support import mock_app_for_tool_support
from galaxy.managers import workflow_request_state
from galaxy.tool_util.parameters import (
    RequestInternalToolState,
    RequestInternalToWorkflowStateError,
    to_workflow_step_state,
    ToolParameterBundleModel,
)
from galaxy.tool_util.parameters.request import RequestInputRef
from galaxy.tools import create_tool_from_representation
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

    def fail_structured(trans, tool, request_payload):
        raise RequestInternalToWorkflowStateError("broken structured state")

    monkeypatch.setattr(extract, "_legacy_step_inputs_by_id", legacy)
    monkeypatch.setattr(extract, "_structured_step_inputs_by_id", fail_structured)
    job = SimpleNamespace(id=42)
    trans = SimpleNamespace()

    with pytest.raises(RequestInternalToWorkflowStateError, match="broken structured state"):
        extract.step_inputs_by_id(
            trans,
            job,
            request_payload={"parameter": {"src": "hda", "id": 1}},
            fallback_to_legacy_state=True,
            tool=SimpleNamespace(id="some_tool"),
        )

    legacy.assert_not_called()


def test_icj_ambiguous_structured_request_returns_none_and_logs(caplog):
    icj = model.ImplicitCollectionJobs()
    icj.id = 123
    icj.get_job_attributes = Mock(
        return_value=[
            SimpleNamespace(tool_request_id=1),
            SimpleNamespace(tool_request_id=2),
            SimpleNamespace(tool_request_id=2),
        ]
    )

    assert icj.has_ambiguous_structured_request
    assert icj.structured_request is None
    assert "spans multiple tool requests" in caplog.text


def test_unambiguous_id_trichotomy():
    # The shared rule both structured-request sources apply: exactly one ->
    # that id; none or ambiguous -> None (caller degrades to legacy).
    assert workflow_request_state.unambiguous_id({7}) == 7
    assert workflow_request_state.unambiguous_id(set()) is None
    assert workflow_request_state.unambiguous_id({1, 2}) is None


def test_resolve_structured_request_payload_tool_request_historical_fallback():
    # Historical pre-EXEC_STATE tool-request rows: Job.tool_execution_state
    # is NULL but Job.tool_request still carries the authoritative payload.
    tool_request = model.ToolRequest()
    tool_request.request = {"parameter": {"src": "hda", "id": 1}}
    job = SimpleNamespace(tool_execution_state=None, tool_request=tool_request)

    resolved = workflow_request_state.resolve_structured_request(job=job)
    assert resolved is not None
    assert resolved.source == "tool_request"
    assert resolved.payload == {"parameter": {"src": "hda", "id": 1}}


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


# A cat1-shaped built-in (matches tools/filters/catWrapper.xml: id "cat1",
# single "input1" data param). Profile 24.2 so the structured parameter model
# is generated.
CAT1_XML = """<tool id="cat1" name="Concatenate datasets" version="1.0.0" profile="24.2">
    <command><![CDATA[cat '$input1' > '$out_file1']]></command>
    <inputs>
        <param name="input1" format="data" type="data" label="Concatenate Dataset"/>
    </inputs>
    <outputs>
        <data name="out_file1" format_source="input1"/>
    </outputs>
</tool>
"""


def test_tool_from_persisted_source_drives_workflow_step_state():
    # Pins TOOL_FROM_SOURCE: a ToolRequest persists only `source` +
    # `source_class` (model ToolSource has no tool_dir/tool_id). At extraction
    # time the tool must be rebuilt from that blob alone -- no toolbox, no
    # job, tool_dir=None, guid=None -- and still yield a `.parameters` model
    # that drives the exact pipeline _structured_step_inputs_by_id runs.
    app = mock_app_for_tool_support()
    original = create_tool_from_representation(app, CAT1_XML, tool_source_class="XmlToolSource")

    # Mirror services/jobs.py: only these two are stored on the ToolRequest.
    persisted_source = original.tool_source.to_string()
    persisted_class = type(original.tool_source).__name__

    rebuilt = create_tool_from_representation(
        app,
        persisted_source,
        tool_dir=None,
        tool_source_class=persisted_class,
        guid=None,
    )
    assert rebuilt.id == "cat1"
    assert rebuilt.version == "1.0.0"
    assert rebuilt.parameters is not None

    parameter_bundle = ToolParameterBundleModel(parameters=rebuilt.parameters)
    request_internal_state = RequestInternalToolState({"input1": {"src": "hda", "id": 1}})
    request_internal_state.validate(parameter_bundle, f"{rebuilt.id} (request internal model)")
    workflow_state = to_workflow_step_state(request_internal_state, parameter_bundle)

    assert workflow_state.input_state == {"input1": {"__class__": "ConnectedValue"}}
