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

from galaxy.tool_util_models.parameters import (
    CwlRecordParameterModel,
    ToolParameterBundle,
)

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


def _fill_defaults(container: dict, parameters: List, only_nullable: bool = False) -> None:
    """Fill null for missing nullable params, recursively into nested types.

    If only_nullable, skip params that have defaults (for job_internal semantics
    where Galaxy fills None only for nullable-no-default params).
    """
    for param in parameters:
        if param.name not in container and not param.request_requires_value:
            if only_nullable and param.has_default:
                continue
            container[param.name] = None
        elif param.name in container:
            _fill_value(container[param.name], param, only_nullable=only_nullable)


def _match_record_variant(value: dict, record_members: List) -> Optional[CwlRecordParameterModel]:
    """Pick the record variant matching value via single-symbol enum discriminator.

    Scans each record's fields for a cwl_enum field with exactly 1 symbol.
    If that field exists in value and its value matches the symbol, return that record.
    Falls back to first record if no discriminator found.
    """
    for record in record_members:
        for field in record.fields:
            if field.parameter_type == "cwl_enum" and len(field.symbols) == 1:
                expected = field.symbols[0]
                if field.name in value and value[field.name] == expected:
                    return record
    # No discriminator matched — fall back to first record
    return record_members[0]


def _fill_value(value, param, only_nullable: bool = False) -> None:
    """Recursively fill defaults for a value based on its parameter type."""
    ptype = param.parameter_type
    if ptype == "cwl_record" and isinstance(value, dict):
        _fill_defaults(value, param.fields, only_nullable=only_nullable)
    elif ptype == "cwl_array" and isinstance(value, list):
        for item in value:
            _fill_value(item, param.item_type, only_nullable=only_nullable)
    elif ptype == "cwl_union" and value is not None:
        record_members = [m for m in param.parameters if m.parameter_type == "cwl_record"]
        if isinstance(value, dict) and record_members:
            matched = _match_record_variant(value, record_members)
            if matched is not None:
                _fill_defaults(value, matched.fields, only_nullable=only_nullable)
        elif isinstance(value, list):
            for member in param.parameters:
                if member.parameter_type == "cwl_array":
                    for item in value:
                        _fill_value(item, member.item_type, only_nullable=only_nullable)
                    break


def cwl_job_to_internal(job_dict: dict, input_models: ToolParameterBundle) -> dict:
    """Convert CWL job dict for job_internal validation.

    Like cwl_job_to_request(encode_id=False) but also fills None for
    nullable-no-default params (Galaxy fills these before job_internal validation).
    """
    from galaxy.tool_util.cwl.job_conversion import cwl_job_to_request

    result = cwl_job_to_request(job_dict, input_models, encode_id=False)
    _fill_defaults(result, input_models.parameters, only_nullable=True)
    return result
