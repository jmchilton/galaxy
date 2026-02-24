"""Test runtimeify() for CWL parameter types.

Validates job_internal -> runtimeify() -> job_runtime state transition
for CWL parameter types using mock adapt_dataset callbacks (no Galaxy
app context needed).
"""

from galaxy.tool_util.parameters import (
    JobInternalToolState,
    validate_internal_job,
)
from galaxy.tool_util.parameters.convert import runtimeify
from galaxy.tool_util.unittest_utils.parameters import parameter_bundle_for_file
from galaxy.tool_util_models.parameters import (
    DataInternalJson,
    DataRequestInternalDereferencedT,
)


def _mock_adapt_dataset(value: DataRequestInternalDereferencedT) -> DataInternalJson:
    """Mock adapt_dataset returning valid DataInternalJson for any HDA ref."""
    return DataInternalJson(
        **{
            "class": "File",
            "basename": f"input_{value.id}.txt",
            "location": "step_input://0",
            "path": f"/tmp/datasets/input_{value.id}.txt",
            "nameroot": f"input_{value.id}",
            "nameext": ".txt",
            "format": "txt",
            "size": 1024,
        }
    )


def _mock_adapt_collection(value, collection_type):
    raise NotImplementedError("Collection adaptation not expected in these tests")


def _do_runtimeify(tool_name, job_internal_dict):
    """Validate job_internal, runtimeify, return runtime state dict.

    runtimeify() internally validates against job_runtime model, so if
    this returns without error, the transition produced valid runtime state.
    """
    bundle = parameter_bundle_for_file(tool_name)
    validate_internal_job(bundle, job_internal_dict)
    job_internal = JobInternalToolState(job_internal_dict)
    runtime_state = runtimeify(job_internal, bundle, _mock_adapt_dataset, _mock_adapt_collection)
    return runtime_state.input_state


# -- CWL File --


def test_runtimeify_cwl_file():
    """CWL File: {src: hda, id: N} -> CwlFileRuntimeJson."""
    result = _do_runtimeify("cwl_file", {"parameter": {"src": "hda", "id": 5}})
    param = result["parameter"]
    assert param["class"] == "File"
    assert param["basename"] == "input_5.txt"
    assert param["location"] == "step_input://0"
    assert param["nameroot"] == "input_5"
    assert param["nameext"] == ".txt"


# -- CWL Directory --


def test_runtimeify_cwl_directory():
    """CWL Directory: {src: hda, id: N} -> CwlDirectoryRuntimeJson."""
    result = _do_runtimeify("cwl_directory", {"parameter": {"src": "hda", "id": 5}})
    param = result["parameter"]
    assert param["class"] == "Directory"
    assert param["basename"] == "input_5.txt"
    assert param["location"] == "step_input://0"


# -- CWL File Array --


def test_runtimeify_cwl_file_array():
    """Array of Files: each element adapted independently."""
    result = _do_runtimeify(
        "cwl_file_array",
        {
            "parameter": [
                {"src": "hda", "id": 5},
                {"src": "hda", "id": 6},
            ]
        },
    )
    arr = result["parameter"]
    assert len(arr) == 2
    assert arr[0]["class"] == "File"
    assert arr[0]["basename"] == "input_5.txt"
    assert arr[1]["basename"] == "input_6.txt"


# -- CWL Record with File --


def test_runtimeify_cwl_record_with_file():
    """Record containing File + scalar: only file field adapted."""
    result = _do_runtimeify(
        "cwl_record_with_file", {"parameter": {"name": "hello", "input_file": {"src": "hda", "id": 5}}}
    )
    rec = result["parameter"]
    assert rec["name"] == "hello"
    assert rec["input_file"]["class"] == "File"
    assert rec["input_file"]["basename"] == "input_5.txt"


# -- CWL Optional File (null|File union) --


def test_runtimeify_cwl_file_optional_with_file():
    """Optional File with a file value -> adapted to CwlFileRuntimeJson."""
    result = _do_runtimeify("cwl_file_optional", {"parameter": {"src": "hda", "id": 5}})
    param = result["parameter"]
    assert param["class"] == "File"
    assert param["basename"] == "input_5.txt"


def test_runtimeify_cwl_file_optional_null():
    """Optional File with null -> passes through unchanged."""
    result = _do_runtimeify("cwl_file_optional", {"parameter": None})
    assert result["parameter"] is None


# -- Scalar passthrough (no adaptation expected) --


def test_runtimeify_cwl_int_no_change():
    """Non-file CWL type: runtimeify is a no-op, value passes through."""
    bundle = parameter_bundle_for_file("cwl_int")
    job_internal_dict = {"parameter": 42}
    validate_internal_job(bundle, job_internal_dict)
    job_internal = JobInternalToolState(job_internal_dict)
    runtime_state = runtimeify(job_internal, bundle, _mock_adapt_dataset, _mock_adapt_collection)
    assert runtime_state.input_state["parameter"] == 42
