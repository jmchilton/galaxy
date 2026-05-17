from typing import (
    Any,
    Dict,
    Optional,
)

import pytest

from galaxy.tool_util.parameters import (
    DataRequestCollectionUri,
    DataRequestInternalHda,
    DataRequestInternalHdca,
    DataRequestUri,
    decode,
    dereference,
    encode,
    fill_static_defaults,
    from_workflow_execution_state,
    input_models_for_tool_source,
    landing_decode,
    landing_encode,
    LandingRequestToolState,
    MappedCollectionInput,
    RelaxedRequestToolState,
    RequestInternalToWorkflowStateError,
    RequestInternalDereferencedToolState,
    RequestInternalToolState,
    RequestToolState,
    strictify,
    to_workflow_step_state,
)
from galaxy.tool_util.parameters.request import (
    RequestInputRef,
    RequestUrlInputRef,
    request_internal_input_refs,
    request_internal_url_inputs,
)
from galaxy.tool_util.parser.util import parse_profile_version
from .test_parameter_test_cases import tool_source_for

EXAMPLE_ID_1_ENCODED = "123456789abcde"
EXAMPLE_ID_1 = 13
EXAMPLE_ID_2_ENCODED = "123456789abcd2"
EXAMPLE_ID_2 = 14

ID_MAP: Dict[int, str] = {
    EXAMPLE_ID_1: EXAMPLE_ID_1_ENCODED,
    EXAMPLE_ID_2: EXAMPLE_ID_2_ENCODED,
}


def test_decode_data():
    tool_source = tool_source_for("parameters/gx_data")
    bundle = input_models_for_tool_source(tool_source)
    request_state = RequestToolState({"parameter": {"src": "hda", "id": EXAMPLE_ID_1_ENCODED}})
    request_state.validate(bundle)
    decoded_state = decode(request_state, bundle, _fake_decode)
    assert decoded_state.input_state["parameter"]["src"] == "hda"
    assert decoded_state.input_state["parameter"]["id"] == EXAMPLE_ID_1


def test_decode_data_batch():
    tool_source = tool_source_for("parameters/gx_data")
    bundle = input_models_for_tool_source(tool_source)
    request_state = RequestToolState(
        {"parameter": {"__class__": "Batch", "values": [{"src": "hda", "id": EXAMPLE_ID_1_ENCODED}]}}
    )
    request_state.validate(bundle)
    decoded_state = decode(request_state, bundle, _fake_decode)
    assert decoded_state.input_state["parameter"]["values"][0]["src"] == "hda"
    assert decoded_state.input_state["parameter"]["values"][0]["id"] == EXAMPLE_ID_1


def test_to_workflow_step_state_data():
    tool_source = tool_source_for("parameters/gx_data")
    bundle = input_models_for_tool_source(tool_source)
    internal_state = RequestInternalToolState({"parameter": {"src": "hda", "id": EXAMPLE_ID_1}})

    workflow_state = to_workflow_step_state(internal_state, bundle)

    assert workflow_state.input_state == {"parameter": {"__class__": "ConnectedValue"}}


def test_to_workflow_step_state_data_batch():
    tool_source = tool_source_for("parameters/gx_data")
    bundle = input_models_for_tool_source(tool_source)
    internal_state = RequestInternalToolState(
        {"parameter": {"__class__": "Batch", "values": [{"src": "hdca", "id": EXAMPLE_ID_1}], "linked": True}}
    )

    workflow_state = to_workflow_step_state(internal_state, bundle)

    assert workflow_state.input_state == {"parameter": {"__class__": "ConnectedValue"}}


def test_to_workflow_step_state_multiple_data():
    tool_source = tool_source_for("parameters/gx_data_multiple")
    bundle = input_models_for_tool_source(tool_source)
    internal_state = RequestInternalToolState(
        {
            "parameter": [
                {"src": "hda", "id": EXAMPLE_ID_1},
                {"src": "hda", "id": EXAMPLE_ID_2},
            ]
        }
    )

    workflow_state = to_workflow_step_state(internal_state, bundle)

    assert workflow_state.input_state == {"parameter": {"__class__": "ConnectedValue"}}


def test_to_workflow_step_state_cross_product_batch_fails():
    tool_source = tool_source_for("parameters/gx_data")
    bundle = input_models_for_tool_source(tool_source)
    internal_state = RequestInternalToolState(
        {"parameter": {"__class__": "Batch", "values": [{"src": "hdca", "id": EXAMPLE_ID_1}], "linked": False}}
    )

    with pytest.raises(RequestInternalToWorkflowStateError, match="cross-product map-over"):
        to_workflow_step_state(internal_state, bundle)


# ---------------------------------------------------------------------------
# from_workflow_execution_state: synthesize request_internal from the *whole
# step's* resolved input state (connections resolved to concrete {src,id},
# scalars to values) plus the map-over descriptors carried out of collection
# matching. Rederived from the step - never a representative sliced job.
#
#   from_workflow_execution_state(
#       resolved_tool_state: dict,                        # whole-step resolved, {src,id}/scalar leaves
#       mapped_inputs: dict[str, MappedCollectionInput],  # source-neutral map-over descriptors
#       input_models,
#   ) -> RequestInternalToolState
#
# A mapped input is emitted as a length-1 Batch carrying the *parent*
# collection ref (so the forward to_workflow_step_state never trips its
# "exactly one value" guard). Non-mapped inputs pass their resolved value
# straight through. linked is always True on the workflow path; linked=False
# is rejected defensively to stay symmetric with to_workflow_step_state.
# ---------------------------------------------------------------------------


def test_from_workflow_execution_state_data_passthrough():
    tool_source = tool_source_for("parameters/gx_data")
    bundle = input_models_for_tool_source(tool_source)

    internal_state = from_workflow_execution_state(
        {"parameter": {"src": "hda", "id": EXAMPLE_ID_1}},
        {},
        bundle,
    )

    assert isinstance(internal_state, RequestInternalToolState)
    assert internal_state.input_state == {"parameter": {"src": "hda", "id": EXAMPLE_ID_1}}


def test_from_workflow_execution_state_collection_passthrough():
    tool_source = tool_source_for("parameters/gx_data_collection")
    bundle = input_models_for_tool_source(tool_source)

    internal_state = from_workflow_execution_state(
        {"parameter": {"src": "hdca", "id": EXAMPLE_ID_1}},
        {},
        bundle,
    )

    assert internal_state.input_state == {"parameter": {"src": "hdca", "id": EXAMPLE_ID_1}}


def test_from_workflow_execution_state_matched_batch_single_input():
    """A data input mapped over a list collection -> length-1 linked Batch.

    Whatever concrete value sits at a mapped input ({src:hda,id:99} here) is
    ignored; the converter emits the *parent* collection ref from the map-over
    descriptor.
    """
    tool_source = tool_source_for("parameters/gx_data")
    bundle = input_models_for_tool_source(tool_source)

    internal_state = from_workflow_execution_state(
        {"parameter": {"src": "hda", "id": 99}},
        {"parameter": MappedCollectionInput(src="hdca", id=EXAMPLE_ID_1, linked=True)},
        bundle,
    )

    assert internal_state.input_state == {
        "parameter": {"__class__": "Batch", "values": [{"src": "hdca", "id": EXAMPLE_ID_1}], "linked": True}
    }


def test_from_workflow_execution_state_nested_list_paired_subcollection():
    """list:paired subcollection map-over -> Batch value carries map_over_type."""
    tool_source = tool_source_for("parameters/gx_data_collection_list_paired_y")
    bundle = input_models_for_tool_source(tool_source)

    internal_state = from_workflow_execution_state(
        {"parameter": {"src": "dce", "id": 99}},
        {"parameter": MappedCollectionInput(src="hdca", id=EXAMPLE_ID_1, map_over_type="paired", linked=True)},
        bundle,
    )

    assert internal_state.input_state == {
        "parameter": {
            "__class__": "Batch",
            "values": [{"src": "hdca", "id": EXAMPLE_ID_1, "map_over_type": "paired"}],
            "linked": True,
        }
    }


def test_from_workflow_execution_state_multi_input_matched_batch():
    """>=2 batched inputs, all linked:true -> each its own length-1 Batch.

    The per-input descriptors are independent; collection matching keys them
    by input name, so each mapped input synthesizes separately.
    """
    tool_source = tool_source_for("expression_pick_larger_file")
    bundle = input_models_for_tool_source(tool_source)

    internal_state = from_workflow_execution_state(
        {"input1": {"src": "hda", "id": 90}, "input2": {"src": "hda", "id": 91}},
        {
            "input1": MappedCollectionInput(src="hdca", id=EXAMPLE_ID_1, linked=True),
            "input2": MappedCollectionInput(src="hdca", id=EXAMPLE_ID_2, linked=True),
        },
        bundle,
    )

    assert internal_state.input_state == {
        "input1": {"__class__": "Batch", "values": [{"src": "hdca", "id": EXAMPLE_ID_1}], "linked": True},
        "input2": {"__class__": "Batch", "values": [{"src": "hdca", "id": EXAMPLE_ID_2}], "linked": True},
    }


def test_from_workflow_execution_state_cross_product_hard_fail():
    """linked=False is never produced by the workflow path; reject defensively."""
    tool_source = tool_source_for("parameters/gx_data")
    bundle = input_models_for_tool_source(tool_source)

    with pytest.raises(RequestInternalToWorkflowStateError, match="cross-product map-over"):
        from_workflow_execution_state(
            {"parameter": {"src": "hda", "id": 99}},
            {"parameter": MappedCollectionInput(src="hdca", id=EXAMPLE_ID_1, linked=False)},
            bundle,
        )


def test_from_workflow_execution_state_roundtrips_through_to_workflow_step_state():
    """Synthesized matched Batch must survive the forward converter.

    Closes the loop: the length-1 Batch post-condition means
    to_workflow_step_state does not raise "exactly one value" and yields a
    ConnectedValue.
    """
    tool_source = tool_source_for("parameters/gx_data")
    bundle = input_models_for_tool_source(tool_source)

    internal_state = from_workflow_execution_state(
        {"parameter": {"src": "hda", "id": 99}},
        {"parameter": MappedCollectionInput(src="hdca", id=EXAMPLE_ID_1, linked=True)},
        bundle,
    )

    workflow_state = to_workflow_step_state(internal_state, bundle)
    assert workflow_state.input_state == {"parameter": {"__class__": "ConnectedValue"}}


def test_request_internal_input_refs_preserve_workflow_input_names():
    refs = request_internal_input_refs(
        {
            "queries": [
                {"input2": {"src": "hda", "id": EXAMPLE_ID_1}},
                {"input2": {"__class__": "Batch", "values": [{"src": "hdca", "id": EXAMPLE_ID_2}]}},
            ]
        }
    )

    assert RequestInputRef("dataset", EXAMPLE_ID_1, "queries_0|input2", "hda") in refs
    assert RequestInputRef("collection", EXAMPLE_ID_2, "queries_1|input2", "hdca") in refs


def test_request_internal_input_refs_multiple_data_use_formal_input_name():
    refs = request_internal_input_refs(
        {
            "parameter": [
                {"src": "hda", "id": EXAMPLE_ID_1},
                {"src": "hda", "id": EXAMPLE_ID_2},
            ]
        }
    )

    assert refs == [
        RequestInputRef("dataset", EXAMPLE_ID_1, "parameter", "hda"),
        RequestInputRef("dataset", EXAMPLE_ID_2, "parameter", "hda"),
    ]


def test_request_internal_url_inputs_preserve_workflow_input_names():
    refs = request_internal_url_inputs(
        {
            "queries": [
                {
                    "input2": {
                        "src": "url",
                        "url": "https://example.org/data.txt",
                        "ext": "txt",
                    }
                }
            ]
        }
    )

    assert refs == [
        RequestUrlInputRef(
            "queries_0|input2",
            "https://example.org/data.txt",
            {"src": "url", "url": "https://example.org/data.txt", "ext": "txt"},
        )
    ]


def test_decode_collection():
    tool_source = tool_source_for("parameters/gx_data_collection")
    bundle = input_models_for_tool_source(tool_source)
    request_state = RequestToolState({"parameter": {"src": "hdca", "id": EXAMPLE_ID_1_ENCODED}})
    request_state.validate(bundle)
    decoded_state = decode(request_state, bundle, _fake_decode)
    assert decoded_state.input_state["parameter"]["src"] == "hdca"
    assert decoded_state.input_state["parameter"]["id"] == EXAMPLE_ID_1


def test_decode_repeat():
    tool_source = tool_source_for("parameters/gx_repeat_data")
    bundle = input_models_for_tool_source(tool_source)
    request_state = RequestToolState({"parameter": [{"data_parameter": {"src": "hda", "id": EXAMPLE_ID_1_ENCODED}}]})
    request_state.validate(bundle)
    decoded_state = decode(request_state, bundle, _fake_decode)
    assert decoded_state.input_state["parameter"][0]["data_parameter"]["src"] == "hda"
    assert decoded_state.input_state["parameter"][0]["data_parameter"]["id"] == EXAMPLE_ID_1


def test_decode_section():
    tool_source = tool_source_for("parameters/gx_section_data")
    bundle = input_models_for_tool_source(tool_source)
    request_state = RequestToolState({"parameter": {"data_parameter": {"src": "hda", "id": EXAMPLE_ID_1_ENCODED}}})
    request_state.validate(bundle)
    decoded_state = decode(request_state, bundle, _fake_decode)
    assert decoded_state.input_state["parameter"]["data_parameter"]["src"] == "hda"
    assert decoded_state.input_state["parameter"]["data_parameter"]["id"] == EXAMPLE_ID_1


def test_decode_conditional():
    tool_source = tool_source_for("identifier_in_conditional")
    bundle = input_models_for_tool_source(tool_source)
    request_state = RequestToolState(
        {"outer_cond": {"multi_input": False, "input1": {"src": "hda", "id": EXAMPLE_ID_1_ENCODED}}}
    )
    request_state.validate(bundle)
    decoded_state = decode(request_state, bundle, _fake_decode)
    assert decoded_state.input_state["outer_cond"]["input1"]["src"] == "hda"
    assert decoded_state.input_state["outer_cond"]["input1"]["id"] == EXAMPLE_ID_1


def test_multi_data():
    tool_source = tool_source_for("parameters/gx_data_multiple")
    bundle = input_models_for_tool_source(tool_source)
    request_state = RequestToolState(
        {"parameter": [{"src": "hda", "id": EXAMPLE_ID_1_ENCODED}, {"src": "hda", "id": EXAMPLE_ID_2_ENCODED}]}
    )
    request_state.validate(bundle)
    decoded_state = decode(request_state, bundle, _fake_decode)
    assert decoded_state.input_state["parameter"][0]["src"] == "hda"
    assert decoded_state.input_state["parameter"][0]["id"] == EXAMPLE_ID_1
    assert decoded_state.input_state["parameter"][1]["src"] == "hda"
    assert decoded_state.input_state["parameter"][1]["id"] == EXAMPLE_ID_2

    encoded_state = encode(decoded_state, bundle, _fake_encode)
    assert encoded_state.input_state["parameter"][0]["src"] == "hda"
    assert encoded_state.input_state["parameter"][0]["id"] == EXAMPLE_ID_1_ENCODED
    assert encoded_state.input_state["parameter"][1]["src"] == "hda"
    assert encoded_state.input_state["parameter"][1]["id"] == EXAMPLE_ID_2_ENCODED


def test_encode_optional_data_collection_none():
    tool_source = tool_source_for("parameters/gx_data_collection_optional")
    bundle = input_models_for_tool_source(tool_source)
    internal_state = RequestInternalToolState({"parameter": None})
    encoded_state = encode(internal_state, bundle, _fake_encode)
    assert encoded_state.input_state["parameter"] is None


def test_landing_encode_data():
    tool_source = tool_source_for("parameters/gx_data")
    bundle = input_models_for_tool_source(tool_source)
    request_state = LandingRequestToolState({"parameter": {"src": "hda", "id": EXAMPLE_ID_1_ENCODED}})
    request_state.validate(bundle)
    decoded_state = landing_decode(request_state, bundle, _fake_decode)
    assert decoded_state.input_state["parameter"]["src"] == "hda"
    assert decoded_state.input_state["parameter"]["id"] == EXAMPLE_ID_1

    encoded_state = landing_encode(decoded_state, bundle, _fake_encode)
    assert encoded_state.input_state["parameter"]["src"] == "hda"
    assert encoded_state.input_state["parameter"]["id"] == EXAMPLE_ID_1_ENCODED


def test_landing_encode_data_batch():
    tool_source = tool_source_for("parameters/gx_data")
    bundle = input_models_for_tool_source(tool_source)
    request_state = LandingRequestToolState(
        {"parameter": {"__class__": "Batch", "values": [{"src": "hda", "id": EXAMPLE_ID_1_ENCODED}]}}
    )
    request_state.validate(bundle)
    decoded_state = landing_decode(request_state, bundle, _fake_decode)
    assert decoded_state.input_state["parameter"]["values"][0]["src"] == "hda"
    assert decoded_state.input_state["parameter"]["values"][0]["id"] == EXAMPLE_ID_1

    encoded_state = landing_encode(decoded_state, bundle, _fake_encode)
    assert encoded_state.input_state["parameter"]["values"][0]["src"] == "hda"
    assert encoded_state.input_state["parameter"]["values"][0]["id"] == EXAMPLE_ID_1_ENCODED


def test_dereference():
    tool_source = tool_source_for("parameters/gx_data")
    bundle = input_models_for_tool_source(tool_source)
    raw_request_state = {"parameter": {"src": "url", "url": "gxfiles://mystorage/1.bed", "ext": "bed"}}
    request_state = RequestInternalToolState(raw_request_state)
    request_state.validate(bundle)

    exception: Optional[Exception] = None
    try:
        # quickly verify this request needs to be dereferenced
        bad_state = RequestInternalDereferencedToolState(raw_request_state)
        bad_state.validate(bundle)
    except Exception as e:
        exception = e
    assert exception is not None

    dereferenced_state = dereference(request_state, bundle, _fake_dereference, _fake_collection_deference)
    assert isinstance(dereferenced_state, RequestInternalDereferencedToolState)
    dereferenced_state.validate(bundle)


def test_fill_defaults():
    with_defaults = fill_state_for({}, "parameters/gx_int")
    assert with_defaults["parameter"] == 1
    with_defaults = fill_state_for({}, "parameters/gx_float")
    assert with_defaults["parameter"] == 1.0
    with_defaults = fill_state_for({}, "parameters/gx_boolean")
    assert with_defaults["parameter"] is False
    with_defaults = fill_state_for({}, "parameters/gx_boolean_optional")
    # This is False unfortunately - see comments in gx_boolean_optional XML.
    assert with_defaults["parameter"] is False
    with_defaults = fill_state_for({}, "parameters/gx_boolean_checked")
    assert with_defaults["parameter"] is True
    with_defaults = fill_state_for({}, "parameters/gx_boolean_optional_checked")
    assert with_defaults["parameter"] is True

    with_defaults = fill_state_for({}, "parameters/gx_conditional_boolean")
    assert with_defaults["conditional_parameter"]["test_parameter"] is False
    assert with_defaults["conditional_parameter"]["boolean_parameter"] is False

    with_defaults = fill_state_for({"conditional_parameter": {}}, "parameters/gx_conditional_boolean")
    assert with_defaults["conditional_parameter"]["test_parameter"] is False
    assert with_defaults["conditional_parameter"]["boolean_parameter"] is False

    with_defaults = fill_state_for({}, "parameters/gx_repeat_boolean")
    assert len(with_defaults["parameter"]) == 0
    with_defaults = fill_state_for({"parameter": [{}]}, "parameters/gx_repeat_boolean")
    assert len(with_defaults["parameter"]) == 1
    instance_state = with_defaults["parameter"][0]
    assert instance_state["boolean_parameter"] is False

    with_defaults = fill_state_for({}, "parameters/gx_repeat_boolean_min")
    assert len(with_defaults["parameter"]) == 2
    assert with_defaults["parameter"][0]["boolean_parameter"] is False
    assert with_defaults["parameter"][1]["boolean_parameter"] is False
    with_defaults = fill_state_for({"parameter": [{}, {}]}, "parameters/gx_repeat_boolean_min")
    assert len(with_defaults["parameter"]) == 2
    assert with_defaults["parameter"][0]["boolean_parameter"] is False
    assert with_defaults["parameter"][1]["boolean_parameter"] is False
    with_defaults = fill_state_for({"parameter": [{}]}, "parameters/gx_repeat_boolean_min")
    assert with_defaults["parameter"][0]["boolean_parameter"] is False
    assert with_defaults["parameter"][1]["boolean_parameter"] is False

    with_defaults = fill_state_for({}, "parameters/gx_section_boolean")
    assert with_defaults["parameter"]["boolean_parameter"] is False

    with_defaults = fill_state_for({}, "parameters/gx_drill_down_exact_with_selection")
    assert with_defaults["parameter"] == "aba"

    with_defaults = fill_state_for({}, "parameters/gx_hidden")
    assert with_defaults["parameter"] == "moo"

    with_defaults = fill_state_for({}, "parameters/gx_genomebuild_optional")
    assert with_defaults["parameter"] is None

    with_defaults = fill_state_for({}, "parameters/gx_select")
    assert with_defaults["parameter"] == "--ex1"

    with_defaults = fill_state_for({}, "parameters/gx_select_optional")
    assert with_defaults["parameter"] is None

    with_defaults = fill_state_for({}, "parameters/gx_select_multiple")
    assert with_defaults["parameter"] is None

    with_defaults = fill_state_for({}, "parameters/gx_select_multiple_optional")
    assert with_defaults["parameter"] is None

    with_defaults = fill_state_for({}, "parameters/gx_select_multiple_one_default")
    assert with_defaults["parameter"] == ["--ex3"]

    # Do not fill in dynamic defaults... these require a Galaxy runtime.
    with_defaults = fill_state_for({}, "remove_value", partial=True)
    assert "choose_value" not in with_defaults

    with_defaults = fill_state_for(
        {"single": {"src": "hda", "id": 4}}, "select_from_dataset_in_conditional", partial=True
    )
    assert with_defaults["cond"]["cond"] == "single"
    assert with_defaults["cond"]["inner_cond"]["inner_cond"] == "single"

    # dynamic parameters should just stay empty - null would cause runtime to skip over population
    with_defaults = fill_state_for({}, "parameters/gx_select_dynamic", partial=True)
    assert "parameter" not in with_defaults

    # dynamic parameters should just stay empty - null would cause runtime to skip over population
    with_defaults = fill_state_for(
        {"conditional_parameter": {"test_parameter": False}},
        "parameters/gx_conditional_boolean_discriminate_on_string_value",
    )
    assert "conditional_parameter" in with_defaults
    assert "boolean_parameter" in with_defaults["conditional_parameter"]
    assert with_defaults["conditional_parameter"]["boolean_parameter"] is False


def test_strictify():
    strict_state = strictify_for({"parameter": 1}, "parameters/gx_int")
    assert strict_state["parameter"] == 1

    strict_state = strictify_for({}, "parameters/gx_text_optional_false")
    assert strict_state["parameter"] == ""

    strict_state = strictify_for({"parameter": None}, "parameters/gx_text_optional_false")
    assert strict_state["parameter"] == ""


def strictify_for(tool_state: Dict[str, Any], tool_path: str) -> Dict[str, Any]:
    tool_source = tool_source_for(tool_path)
    bundle = input_models_for_tool_source(tool_source)
    relaxed_state = RelaxedRequestToolState(tool_state)
    relaxed_state.validate(bundle)
    return strictify(relaxed_state, bundle).input_state


def _fake_dereference(input: DataRequestUri) -> DataRequestInternalHda:
    return DataRequestInternalHda(id=EXAMPLE_ID_1, src="hda")


def _fake_collection_deference(input: DataRequestCollectionUri) -> DataRequestInternalHdca:
    return DataRequestInternalHdca(id=EXAMPLE_ID_1, src="hdca")


def _fake_decode(input: str) -> int:
    return next(key for key, value in ID_MAP.items() if value == input)


def _fake_encode(input: int) -> str:
    return ID_MAP[input]


def fill_state_for(tool_state: Dict[str, Any], tool_path: str, partial: bool = False) -> Dict[str, Any]:
    tool_source = tool_source_for(tool_path)
    bundle = input_models_for_tool_source(tool_source)
    profile = parse_profile_version(tool_source)
    internal_state = fill_static_defaults(tool_state, bundle, profile, partial=partial)
    return internal_state
