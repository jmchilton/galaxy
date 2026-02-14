"""Convert CWL conformance job dicts to Galaxy request format.

Walks parameter models to convert CWL File/Directory refs ({class: File, ...})
to Galaxy data refs ({src: "hda", id: ...}), strips CWL meta-fields and
extra keys not in tool params.
"""

import copy
from typing import (
    Any,
    Callable,
    List,
)

from galaxy.tool_util_models.parameters import ToolParameterBundle

# CWL meta-fields in job dicts that are not tool parameters
CWL_JOB_META_FIELDS = {"cwl:requirements", "cwl:defaults"}


def cwl_job_to_request(
    job_dict: dict,
    input_models: ToolParameterBundle,
    encode_id: bool = True,
) -> dict:
    """Convert CWL conformance job dict to Galaxy request format.

    - File/Directory refs -> {src: "hda", id: <encoded_or_int>}
    - Strip CWL meta-fields
    - Strip extra job keys not in tool params
    - Do NOT fill defaults
    """
    job = copy.deepcopy(job_dict)

    for field in CWL_JOB_META_FIELDS:
        job.pop(field, None)

    param_names = {p.name for p in input_models.parameters}
    for key in list(job.keys()):
        if key not in param_names:
            del job[key]

    counter = [0]

    def next_id() -> Any:
        counter[0] += 1
        if encode_id:
            return _encode_fake_id(counter[0])
        return counter[0]

    _convert_file_refs(job, input_models.parameters, next_id)
    return job


def _encode_fake_id(int_id: int) -> str:
    return f"fake{int_id:04x}ff"


def _convert_file_refs(container: dict, parameters: List, next_id_fn: Callable) -> None:
    for param in parameters:
        if param.name not in container:
            continue
        value = container[param.name]
        if value is None:
            continue
        container[param.name] = _convert_value(value, param, next_id_fn)


def _convert_value(value: Any, param: Any, next_id_fn: Callable) -> Any:
    ptype = param.parameter_type
    if ptype in ("cwl_file", "cwl_directory"):
        if value is None:
            return None
        return {"src": "hda", "id": next_id_fn()}
    elif ptype == "cwl_array":
        if isinstance(value, list):
            return [_convert_value(v, param.item_type, next_id_fn) for v in value]
        return value
    elif ptype == "cwl_record":
        if isinstance(value, dict):
            result = dict(value)
            _convert_file_refs(result, param.fields, next_id_fn)
            return result
        return value
    elif ptype == "cwl_union":
        return _convert_union_value(value, param, next_id_fn)
    elif ptype == "cwl_any":
        return _convert_any_value(value, next_id_fn)
    return value


def _convert_union_value(value: Any, param: Any, next_id_fn: Callable) -> Any:
    if value is None:
        return None
    # Check if value looks like a CWL File/Directory dict
    if isinstance(value, dict) and "class" in value:
        cls = value.get("class")
        for member in param.parameters:
            if member.parameter_type == "cwl_file" and cls == "File":
                return {"src": "hda", "id": next_id_fn()}
            if member.parameter_type == "cwl_directory" and cls == "Directory":
                return {"src": "hda", "id": next_id_fn()}
    # Check for record members
    for member in param.parameters:
        if member.parameter_type == "cwl_record" and isinstance(value, dict):
            result = dict(value)
            _convert_file_refs(result, member.fields, next_id_fn)
            return result
        if member.parameter_type == "cwl_array" and isinstance(value, list):
            return [_convert_value(v, member.item_type, next_id_fn) for v in value]
    return value


def _convert_any_value(value: Any, next_id_fn: Callable) -> Any:
    """Recursively convert File/Directory dicts within Any-typed values."""
    if isinstance(value, dict) and value.get("class") in ("File", "Directory"):
        return {"src": "hda", "id": next_id_fn()}
    if isinstance(value, list):
        return [_convert_any_value(v, next_id_fn) for v in value]
    if isinstance(value, dict):
        return {k: _convert_any_value(v, next_id_fn) for k, v in value.items()}
    return value
