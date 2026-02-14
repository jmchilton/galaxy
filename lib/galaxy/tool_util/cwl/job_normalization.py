"""Normalize CWL job dicts for validation against CWL runtime models.

Applies cwltool's normalization pipeline (path->location, basename/nameroot/nameext
derivation) without requiring filesystem access.
"""

import copy
from typing import (
    List,
    Optional,
)

from cwltool.utils import (
    normalizeFilesDirs,
    visit_class,
)

from galaxy.tool_util_models.parameters import ToolParameterBundle

# CWL meta-fields in job dicts that are not tool parameters
CWL_JOB_META_FIELDS = {"cwl:requirements", "cwl:defaults"}


def normalize_cwl_job(job_dict: dict, input_models: Optional[ToolParameterBundle] = None) -> dict:
    """Expand CWL job dict File/Directory objects for validation.

    Applies cwltool's normalization:
    1. Strip CWL meta-fields (cwl:requirements etc.)
    2. path -> location conversion
    3. basename/nameroot/nameext derivation from location
    4. If input_models provided, fill null for missing nullable params
    """
    job = copy.deepcopy(job_dict)

    # Strip CWL meta-fields
    for field in CWL_JOB_META_FIELDS:
        job.pop(field, None)

    def path_to_loc(p):
        if "location" not in p and "path" in p:
            p["location"] = p["path"]
            del p["path"]

    visit_class(job, ("File", "Directory"), path_to_loc)
    normalizeFilesDirs(job)

    if input_models is not None:
        _fill_defaults(job, input_models.parameters)
        # Strip job keys not in tool params (CWL allows extras, strict models don't)
        param_names = {p.name for p in input_models.parameters}
        for key in list(job.keys()):
            if key not in param_names:
                del job[key]

    return job


def _fill_defaults(container: dict, parameters: List) -> None:
    """Fill null for missing nullable params, recursively into nested types."""
    for param in parameters:
        if param.name not in container and not param.request_requires_value:
            container[param.name] = None
        elif param.name in container:
            _fill_value(container[param.name], param)


def _fill_value(value, param) -> None:
    """Recursively fill defaults for a value based on its parameter type."""
    ptype = param.parameter_type
    if ptype == "cwl_record" and isinstance(value, dict):
        _fill_defaults(value, param.fields)
    elif ptype == "cwl_array" and isinstance(value, list):
        for item in value:
            _fill_value(item, param.item_type)
    elif ptype == "cwl_union" and value is not None:
        # Try to fill record/array members if value matches their shape
        for member in param.parameters:
            if member.parameter_type == "cwl_record" and isinstance(value, dict):
                _fill_defaults(value, member.fields)
                break
            elif member.parameter_type == "cwl_array" and isinstance(value, list):
                for item in value:
                    _fill_value(item, member.item_type)
                break
