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


def test_resolve_structured_request_via_icj_direct_link():
    # ICJ carries the canonical TES link for mapped executions; resolver
    # reads through it directly with no per-job aggregation.
    tes = model.ToolExecutionState(
        request={"parameter": {"src": "hda", "id": 1}},
        state=workflow_request_state.VALIDATED_REQUEST_STATE,
    )
    tes.id = 42
    icj = model.ImplicitCollectionJobs()
    icj.id = 123
    icj.tool_execution_state = tes

    resolved = workflow_request_state.resolve_structured_request(icj=icj)
    assert resolved.state == workflow_request_state.ResolutionState.VALIDATED
    assert resolved.source_id == 42
    assert resolved.payload == {"parameter": {"src": "hda", "id": 1}}
    assert resolved.tool_execution_state is tes


def test_resolve_structured_request_via_tool_request_link():
    # Tool-request mint anchors the TES on the ToolRequest; resolver
    # reads through tool_request.tool_execution_state.
    tes = model.ToolExecutionState(
        request={"parameter": {"src": "hda", "id": 7}},
        state=workflow_request_state.VALIDATED_REQUEST_STATE,
    )
    tes.id = 99
    tool_request = model.ToolRequest()
    tool_request.tool_execution_state = tes

    resolved = workflow_request_state.resolve_structured_request(tool_request=tool_request)
    assert resolved.state == workflow_request_state.ResolutionState.VALIDATED
    assert resolved.source_id == 99
    assert resolved.payload == {"parameter": {"src": "hda", "id": 7}}
    assert resolved.tool_execution_state is tes


def test_resolve_structured_request_not_validated_keeps_source_id():
    # The non-VALIDATED branch still carries TES.id so consumers can name
    # the producer for diagnostics; payload remains None.
    tes = model.ToolExecutionState(request={"x": 1}, state="not_validated")
    tes.id = 5
    icj = model.ImplicitCollectionJobs()
    icj.tool_execution_state = tes

    resolved = workflow_request_state.resolve_structured_request(icj=icj)
    assert resolved.state == workflow_request_state.ResolutionState.NOT_VALIDATED
    assert resolved.source_id == 5
    assert resolved.payload is None
    assert resolved.tool_execution_state is tes


def test_resolve_structured_request_validation_failed_keeps_source_id():
    tes = model.ToolExecutionState(request=None, state="validation_failed")
    tes.id = 7
    icj = model.ImplicitCollectionJobs()
    icj.tool_execution_state = tes

    resolved = workflow_request_state.resolve_structured_request(icj=icj)
    assert resolved.state == workflow_request_state.ResolutionState.VALIDATION_FAILED
    assert resolved.source_id == 7
    assert resolved.payload is None
    assert resolved.tool_execution_state is tes


def test_resolve_structured_request_missing_when_tes_absent():
    icj = model.ImplicitCollectionJobs()
    icj.tool_execution_state = None

    resolved = workflow_request_state.resolve_structured_request(icj=icj)
    assert resolved.state == workflow_request_state.ResolutionState.MISSING
    assert resolved.source_id is None
    assert resolved.payload is None
    assert resolved.tool_execution_state is None


def test_resolve_structured_request_job_walks_to_workflow_invocation_step_tes():
    # Workflow tool steps always mint a WIS-side TES (validated or not), but
    # execute.py only propagates the link to the Job for VALIDATED captures.
    # The resolver must walk Job -> WIS -> TES for non-VALIDATED captures so
    # the producer stays orderable by TES.id rather than dropping to legacy
    # Job.id space (which would mis-wire post-rollout workflows mixing
    # validated and validation-failed steps).
    tes = model.ToolExecutionState(request=None, state="validation_failed")
    tes.id = 77
    wis = model.WorkflowInvocationStep()
    wis.tool_execution_state = tes
    job = SimpleNamespace(
        implicit_collection_jobs_association=None,
        tool_execution_state=None,
        workflow_invocation_step=wis,
    )

    resolved = workflow_request_state.resolve_structured_request(job=job)
    assert resolved.state == workflow_request_state.ResolutionState.VALIDATION_FAILED
    assert resolved.source_id == 77
    assert resolved.payload is None


def test_resolve_structured_request_job_direct_link_preferred_over_wis():
    # When a Job carries its own TES link (tool-request-sourced standalone
    # job), the resolver uses it directly without consulting the WIS path.
    direct = model.ToolExecutionState(request={"x": 1}, state=workflow_request_state.VALIDATED_REQUEST_STATE)
    direct.id = 1
    wis_tes = model.ToolExecutionState(request=None, state="validation_failed")
    wis_tes.id = 2
    wis = model.WorkflowInvocationStep()
    wis.tool_execution_state = wis_tes
    job = SimpleNamespace(
        implicit_collection_jobs_association=None,
        tool_execution_state=direct,
        workflow_invocation_step=wis,
    )

    resolved = workflow_request_state.resolve_structured_request(job=job)
    assert resolved.source_id == 1  # direct link, not the WIS link


def test_resolve_structured_request_validated_with_non_dict_payload_asserts():
    # Data-model invariant: a 'validated' TES carries a dict payload. A
    # non-dict at this point is a write-side bug and the resolver crashes.
    tes = model.ToolExecutionState(request="not a dict", state=workflow_request_state.VALIDATED_REQUEST_STATE)
    tes.id = 1
    icj = model.ImplicitCollectionJobs()
    icj.tool_execution_state = tes

    with pytest.raises(AssertionError, match="validated"):
        workflow_request_state.resolve_structured_request(icj=icj)


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
