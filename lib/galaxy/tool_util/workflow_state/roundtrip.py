"""Reusable round-trip logic for native↔format2 workflow state conversion.

Provides comparison, classification, and full round-trip validation
functions used by both the CLI tools and the test harness.
"""

import argparse
import copy
import json
import logging
import os
import sys
from dataclasses import (
    dataclass,
    field,
)
from enum import Enum
from typing import (
    Any,
    List,
    Optional,
)

from pydantic import BaseModel

from gxformat2.converter import ImportOptions, python_to_workflow
from gxformat2.export import from_galaxy_native

from ._types import GetToolInfo
from .convert import (
    ConversionValidationFailure,
    convert_state_to_format2,
    make_convert_tool_state,
    make_encode_tool_state,
)

log = logging.getLogger(__name__)


# -- Failure classification --


class FailureClass(Enum):
    TOOL_NOT_FOUND = "tool_not_found"
    NATIVE_VALIDATION = "native_validation"
    CONVERSION_ERROR = "conversion_error"
    TYPE_NOT_HANDLED = "type_not_handled"
    FORMAT2_VALIDATION = "format2_validation"
    REIMPORT_ERROR = "reimport_error"
    ROUNDTRIP_MISMATCH = "roundtrip_mismatch"
    SUBWORKFLOW = "subworkflow"
    PARSE_ERROR = "parse_error"
    OTHER = "other"


@dataclass
class StepResult:
    step_id: str
    tool_id: Optional[str]
    success: bool
    failure_class: Optional[FailureClass] = None
    error: Optional[str] = None
    diffs: list[str] = field(default_factory=list)


@dataclass
class RoundTripResult:
    workflow_name: str
    direction: str  # "native_to_format2" or "format2_to_native"
    step_results: list[StepResult] = field(default_factory=list)

    @property
    def success(self) -> bool:
        return all(r.success for r in self.step_results)

    @property
    def failure_summary(self) -> str:
        failures = [r for r in self.step_results if not r.success]
        if not failures:
            return "PASS"
        parts = []
        for f in failures:
            parts.append(
                f"step {f.step_id} ({f.tool_id}): {f.failure_class.value if f.failure_class else 'unknown'} - {f.error}"
            )
        return "; ".join(parts)


# -- Comparison logic --

SKIP_KEYS = {
    "__current_case__",
    "__input_ext",
    "__page__",
    "__rerun_remap_job_id__",
    "__index__",
    "__job_resource",
    "chromInfo",
}


def compare_tool_state(orig: dict, after: dict, path: str = "") -> list[str]:
    """Recursively compare parsed tool_state dicts, skipping bookkeeping keys."""
    diffs = []
    all_keys = set(list(orig.keys()) + list(after.keys()))
    for key in sorted(all_keys):
        if key in SKIP_KEYS:
            continue
        key_path = f"{path}.{key}" if path else key
        orig_val = _try_json_decode(orig.get(key))
        after_val = _try_json_decode(after.get(key))
        if key not in orig:
            if after_val not in (None, "null"):
                diffs.append(f"{key_path}: missing in original, present in roundtripped ({after_val!r})")
        elif key not in after:
            if orig_val not in (None, "null", []) and not _is_connection_marker(orig_val):
                diffs.append(f"{key_path}: present in original ({orig_val!r}), missing in roundtripped")
        elif isinstance(orig_val, dict) and isinstance(after_val, dict):
            diffs.extend(compare_tool_state(orig_val, after_val, key_path))
        elif isinstance(orig_val, list) and isinstance(after_val, list):
            diffs.extend(_compare_list_state(orig_val, after_val, key_path))
        elif not _values_equivalent(orig_val, after_val):
            diffs.append(f"{key_path}: {orig_val!r} != {after_val!r}")
    return diffs


def _compare_list_state(orig: list, after: list, path: str) -> list[str]:
    """Compare lists (e.g. repeat instances) in tool state."""
    diffs = []
    if len(orig) > 0 and isinstance(orig[0], str):
        try:
            orig = [json.loads(v) if isinstance(v, str) else v for v in orig]
        except (json.JSONDecodeError, TypeError):
            pass
    if len(after) > 0 and isinstance(after[0], str):
        try:
            after = [json.loads(v) if isinstance(v, str) else v for v in after]
        except (json.JSONDecodeError, TypeError):
            pass
    if len(orig) != len(after):
        diffs.append(f"{path}: {len(orig)} items vs {len(after)}")
        return diffs
    for i, (o, a) in enumerate(zip(orig, after)):
        item_path = f"{path}[{i}]"
        if isinstance(o, dict) and isinstance(a, dict):
            diffs.extend(compare_tool_state(o, a, item_path))
        elif not _values_equivalent(o, a):
            diffs.append(f"{item_path}: {o!r} != {a!r}")
    return diffs


def _try_json_decode(value):
    """Try to JSON-decode a string value. Returns original if not decodable."""
    if isinstance(value, str):
        try:
            return json.loads(value)
        except (json.JSONDecodeError, TypeError):
            pass
    return value


def _is_connection_marker(value) -> bool:
    """Check if value is a ConnectedValue/RuntimeValue marker."""
    return isinstance(value, dict) and value.get("__class__") in ("ConnectedValue", "RuntimeValue")


def _values_equivalent(a: Any, b: Any) -> bool:
    """Type-aware value comparison (e.g. "5" == 5, "true" == True)."""
    if a == b:
        return True
    try:
        if isinstance(a, str) and isinstance(b, int):
            return int(a) == b
        if isinstance(a, int) and isinstance(b, str):
            return a == int(b)
    except (ValueError, TypeError):
        pass
    try:
        if isinstance(a, str) and isinstance(b, float):
            return float(a) == b
        if isinstance(a, float) and isinstance(b, str):
            return a == float(b)
    except (ValueError, TypeError):
        pass
    if isinstance(a, str) and isinstance(b, bool):
        if b:
            return a.lower() in ("true", "yes")
        else:
            return a.lower() in ("false", "no")
    if isinstance(a, bool) and isinstance(b, str):
        return _values_equivalent(b, a)
    if a == "null" and b is None:
        return True
    if a is None and b == "null":
        return True
    # Multiple select: list form vs comma-delimited string are equivalent
    if isinstance(a, list) and isinstance(b, str):
        return ",".join(str(v) for v in a) == b
    if isinstance(a, str) and isinstance(b, list):
        return a == ",".join(str(v) for v in b)
    return False


def compare_connections(orig_connections: dict, after_connections: dict, path: str = "") -> list[str]:
    """Compare input_connections dicts for topology equivalence."""
    diffs = []
    all_keys = set(list(orig_connections.keys()) + list(after_connections.keys()))
    for key in sorted(all_keys):
        key_path = f"{path}.input_connections.{key}" if path else f"input_connections.{key}"
        if key not in orig_connections:
            diffs.append(f"{key_path}: missing in original")
        elif key not in after_connections:
            diffs.append(f"{key_path}: missing in roundtripped")
        else:
            orig_val = orig_connections[key]
            after_val = after_connections[key]
            if not isinstance(orig_val, list):
                orig_val = [orig_val]
            if not isinstance(after_val, list):
                after_val = [after_val]
            if len(orig_val) != len(after_val):
                diffs.append(f"{key_path}: {len(orig_val)} connections vs {len(after_val)}")
            else:
                for i, (o, a) in enumerate(zip(orig_val, after_val)):
                    if isinstance(o, dict) and isinstance(a, dict):
                        if o.get("id") != a.get("id") or o.get("output_name") != a.get("output_name"):
                            diffs.append(f"{key_path}[{i}]: {o} != {a}")
    return diffs


def compare_steps(orig_step: dict, after_step: dict) -> list[str]:
    """Compare two native workflow steps for functional equivalence."""
    diffs = []
    for key in ["tool_id", "tool_version"]:
        if orig_step.get(key) != after_step.get(key):
            diffs.append(f"{key}: {orig_step.get(key)!r} != {after_step.get(key)!r}")

    orig_ts = orig_step.get("tool_state")
    after_ts = after_step.get("tool_state")
    if orig_ts and after_ts:
        orig_parsed = json.loads(orig_ts) if isinstance(orig_ts, str) else orig_ts
        after_parsed = json.loads(after_ts) if isinstance(after_ts, str) else after_ts
        diffs.extend(compare_tool_state(orig_parsed, after_parsed))

    orig_ic = orig_step.get("input_connections", {})
    after_ic = after_step.get("input_connections", {})
    diffs.extend(compare_connections(orig_ic, after_ic))

    return diffs


# -- Error classification --


def classify_error(e: Exception) -> FailureClass:
    msg = str(e)
    if "Could not resolve tool" in msg or "get_tool_info" in msg.lower():
        return FailureClass.TOOL_NOT_FOUND
    if isinstance(e, ConversionValidationFailure):
        if "not going to convert" in msg and "native" in msg:
            return FailureClass.NATIVE_VALIDATION
        if "not going to convert" in msg and "cleaned" in msg:
            return FailureClass.FORMAT2_VALIDATION
        return FailureClass.CONVERSION_ERROR
    if "Unhandled parameter type" in msg:
        return FailureClass.TYPE_NOT_HANDLED
    if isinstance(e, NotImplementedError):
        if "parameter type" in msg.lower():
            return FailureClass.TYPE_NOT_HANDLED
        return FailureClass.CONVERSION_ERROR
    if "subworkflow" in msg.lower():
        return FailureClass.SUBWORKFLOW
    if isinstance(e, (json.JSONDecodeError, KeyError)):
        return FailureClass.PARSE_ERROR
    return FailureClass.OTHER


# -- Per-step round-trip --


def roundtrip_native_step(
    step: dict,
    step_id: str,
    get_tool_info: GetToolInfo,
) -> StepResult:
    """Try to convert a single native step to format2 state."""
    tool_id = step.get("tool_id")
    step_type = step.get("type", "tool")

    if step_type == "subworkflow":
        return _roundtrip_subworkflow_step(step, step_id, get_tool_info)

    if step_type != "tool" or not tool_id:
        return StepResult(step_id=step_id, tool_id=tool_id, success=True)

    try:
        convert_state_to_format2(step, get_tool_info)
        return StepResult(step_id=step_id, tool_id=tool_id, success=True)
    except Exception as e:
        return StepResult(
            step_id=step_id,
            tool_id=tool_id,
            success=False,
            failure_class=classify_error(e),
            error=str(e),
        )


def _roundtrip_subworkflow_step(
    step: dict,
    step_id: str,
    get_tool_info: GetToolInfo,
) -> StepResult:
    """Recurse into a subworkflow step, validating/converting nested tool steps."""
    subworkflow = step.get("subworkflow")
    if not subworkflow:
        return StepResult(
            step_id=step_id,
            tool_id=None,
            success=False,
            failure_class=FailureClass.SUBWORKFLOW,
            error="Subworkflow step missing 'subworkflow' key",
        )
    nested_results = roundtrip_native_workflow(subworkflow, get_tool_info, f"subworkflow@step{step_id}")
    nested_failures = [r for r in nested_results.step_results if not r.success]
    if nested_failures:
        errors = "; ".join(f"nested step {f.step_id}: {f.error}" for f in nested_failures)
        return StepResult(
            step_id=step_id,
            tool_id=None,
            success=False,
            failure_class=nested_failures[0].failure_class,
            error=f"Subworkflow nested failures: {errors}",
        )
    return StepResult(step_id=step_id, tool_id=None, success=True)


def roundtrip_native_workflow(
    workflow_dict: dict,
    get_tool_info: GetToolInfo,
    workflow_name: str = "",
) -> RoundTripResult:
    """Round-trip a native workflow: try converting each tool step to format2."""
    result = RoundTripResult(workflow_name=workflow_name, direction="native_to_format2")
    steps = workflow_dict.get("steps", {})

    for step_id, step in steps.items():
        step_result = roundtrip_native_step(step, step_id, get_tool_info)
        result.step_results.append(step_result)

    return result


# -- Full round-trip: native → format2 → native' → compare --


def full_roundtrip_native(
    workflow_dict: dict,
    get_tool_info: GetToolInfo,
    workflow_name: str = "",
) -> tuple[RoundTripResult, Optional[list[str]]]:
    """Full round-trip: native → format2 → native' → compare.

    Delegates to roundtrip_validate() and unwraps the result to the
    legacy (RoundTripResult, diffs) tuple for backwards compatibility.
    """
    result = roundtrip_validate(workflow_dict, get_tool_info, workflow_path=workflow_name)
    conversion_result = result.conversion_result or RoundTripResult(
        workflow_name=workflow_name, direction="native_to_format2"
    )
    if result.error:
        conversion_result.step_results.append(
            StepResult(
                step_id="reimport",
                tool_id=None,
                success=False,
                failure_class=FailureClass.REIMPORT_ERROR,
                error=result.error,
            )
        )
        return conversion_result, None
    return conversion_result, result.diffs


def compare_workflow_steps(orig_workflow: dict, after_workflow: dict, path_prefix: str = "") -> list[str]:
    """Compare tool steps between original and roundtripped workflows, recursing into subworkflows."""
    all_diffs = []
    for step_id, orig_step in orig_workflow.get("steps", {}).items():
        step_type = orig_step.get("type", "tool")
        step_path = f"{path_prefix}step {step_id}" if not path_prefix else f"{path_prefix}/step {step_id}"

        if step_type == "subworkflow":
            after_step = after_workflow.get("steps", {}).get(step_id)
            if after_step is None:
                all_diffs.append(f"{step_path}: missing in roundtripped workflow")
                continue
            orig_sub = orig_step.get("subworkflow", {})
            after_sub = after_step.get("subworkflow", {})
            if not after_sub:
                all_diffs.append(f"{step_path}: subworkflow missing in roundtripped")
                continue
            sub_diffs = compare_workflow_steps(orig_sub, after_sub, path_prefix=f"{step_path}:subworkflow/")
            all_diffs.extend(sub_diffs)
        elif step_type == "tool":
            after_step = after_workflow.get("steps", {}).get(step_id)
            if after_step is None:
                all_diffs.append(f"{step_path}: missing in roundtripped workflow")
                continue
            diffs = compare_steps(orig_step, after_step)
            all_diffs.extend([f"{step_path}: {d}" for d in diffs])

    return all_diffs


# -- Shared helpers for format2 export --


def ensure_export_defaults(workflow_dict: dict):
    """Ensure steps have label/annotation fields required by gxformat2 export, recursing into subworkflows."""
    for step in workflow_dict.get("steps", {}).values():
        step.setdefault("label", None)
        step.setdefault("annotation", "")
        if step.get("type") == "subworkflow" and "subworkflow" in step:
            ensure_export_defaults(step["subworkflow"])


def find_matching_native_step(native_workflow: dict, format2_step: dict, format2_index) -> Optional[dict]:
    """Find the native step matching a format2 step by index, then label+tool_id.

    Does NOT fall back to tool_id-only matching — for workflows with duplicate
    tools that would silently match the wrong step.
    """
    step_id = str(format2_index)
    native_steps = native_workflow.get("steps", {})
    if step_id in native_steps:
        return native_steps[step_id]
    tool_id = format2_step.get("tool_id")
    label = format2_step.get("label")
    if label:
        for step in native_steps.values():
            if step.get("label") == label and step.get("tool_id") == tool_id:
                log.debug("Step %s: matched by label+tool_id fallback", format2_index)
                return step
    return None


# -- Round-trip validation (CLI-facing) --


@dataclass
class RoundTripValidationResult:
    """Result of validating a workflow's native→format2→native round-trip."""

    workflow_path: str
    format2_dict: Optional[dict] = None
    reimported_dict: Optional[dict] = None
    conversion_result: Optional[RoundTripResult] = None
    diffs: Optional[list[str]] = None
    error: Optional[str] = None

    @property
    def ok(self) -> bool:
        if self.error:
            return False
        if self.conversion_result and not self.conversion_result.success:
            return False
        return self.diffs is not None and len(self.diffs) == 0

    @property
    def status(self) -> str:
        if self.error:
            return "error"
        if self.conversion_result and not self.conversion_result.success:
            return "conversion_fail"
        if self.diffs is None:
            return "error"
        if len(self.diffs) > 0:
            return "roundtrip_mismatch"
        return "ok"

    @property
    def summary_line(self) -> str:
        status = self.status
        name = os.path.basename(self.workflow_path)
        if status == "ok":
            n_steps = len(self.conversion_result.step_results) if self.conversion_result else 0
            return f"{name}: OK ({n_steps} steps)"
        elif status == "conversion_fail":
            assert self.conversion_result is not None
            failures = [r for r in self.conversion_result.step_results if not r.success]
            return f"{name}: CONVERSION FAIL ({len(failures)} step(s))"
        elif status == "roundtrip_mismatch":
            assert self.diffs is not None
            return f"{name}: MISMATCH ({len(self.diffs)} diff(s))"
        else:
            return f"{name}: ERROR ({self.error})"


def roundtrip_validate(
    workflow_dict: dict,
    get_tool_info: "GetToolInfo",
    workflow_path: str = "",
    strip_bookkeeping: bool = False,
    clean_stale: bool = True,
) -> RoundTripValidationResult:
    """Validate a native workflow survives native→format2→native round-trip.

    Returns a RoundTripValidationResult with the intermediate format2 dict,
    the reimported native dict, and any diffs found.

    If clean_stale is True (default), stale tool_state keys are stripped
    before conversion — these are keys left behind by older tool versions
    or Galaxy serialization bugs that would otherwise cause validation failures.
    """
    from .clean import clean_stale_state, strip_bookkeeping_from_workflow

    result = RoundTripValidationResult(workflow_path=workflow_path)

    if strip_bookkeeping:
        strip_bookkeeping_from_workflow(workflow_dict)

    if clean_stale:
        strip_bookkeeping_from_workflow(workflow_dict)
        clean_stale_state(workflow_dict, get_tool_info)

    workflow_name = os.path.basename(workflow_path) if workflow_path else ""

    # Per-step conversion (validates each tool step can be converted)
    step_result = roundtrip_native_workflow(workflow_dict, get_tool_info, workflow_name)
    result.conversion_result = step_result
    if not step_result.success:
        return result

    # Forward: native → format2 with schema-aware state conversion
    native_copy = copy.deepcopy(workflow_dict)
    ensure_export_defaults(native_copy)
    convert_cb = make_convert_tool_state(get_tool_info)
    format2_dict = from_galaxy_native(native_copy, convert_tool_state=convert_cb)
    result.format2_dict = format2_dict

    # Reverse: format2 → native with schema-aware encoding
    try:
        import_options = ImportOptions()
        import_options.native_state_encoder = make_encode_tool_state(get_tool_info)
        native_prime = python_to_workflow(
            copy.deepcopy(format2_dict), galaxy_interface=None, import_options=import_options
        )
    except Exception as e:
        result.error = f"Reimport failed: {e}"
        return result

    result.reimported_dict = native_prime
    result.diffs = compare_workflow_steps(workflow_dict, native_prime)
    return result


# -- Options model --


class RoundTripValidateOptions(BaseModel):
    workflow_path: str
    tool_source_cache_dir: Optional[str] = None
    verbose: bool = False
    populate_cache: bool = False
    tool_source: str = "auto"
    strip_bookkeeping: bool = False
    output_native: Optional[str] = None
    output_format2: Optional[str] = None

    @classmethod
    def from_namespace(cls, args: argparse.Namespace) -> "RoundTripValidateOptions":
        fields = set(cls.model_fields)
        return cls(**{k: v for k, v in vars(args).items() if k in fields})


# -- Formatters --


def format_validation_text(
    results: List[RoundTripValidationResult],
    verbose: bool = False,
) -> str:
    lines = []
    ok = sum(1 for r in results if r.ok)
    fail = len(results) - ok

    for r in results:
        lines.append(r.summary_line)
        if verbose and r.status == "conversion_fail" and r.conversion_result:
            for sr in r.conversion_result.step_results:
                if not sr.success:
                    fc = sr.failure_class.value if sr.failure_class else "unknown"
                    lines.append(f"  step {sr.step_id} ({sr.tool_id}): [{fc}] {sr.error}")
        if verbose and r.diffs:
            for d in r.diffs:
                lines.append(f"  {d}")
        if verbose and r.error:
            lines.append(f"  {r.error}")

    lines.append("---")
    lines.append(f"Summary: {ok} OK, {fail} FAIL (total {len(results)} workflows)")
    return "\n".join(lines)


# -- Entry point --


def run_roundtrip_validate(options: RoundTripValidateOptions) -> int:
    """Run round-trip validation pipeline. Returns exit code."""
    from ._cli_common import setup_logging
    from .cache import (
        build_tool_info,
        populate_cache,
    )

    setup_logging(options.verbose)
    tool_info = build_tool_info(options.tool_source_cache_dir)

    if options.populate_cache:
        populate_cache(tool_info, options.workflow_path, source=options.tool_source)
        print("", file=sys.stderr)

    is_dir = os.path.isdir(options.workflow_path)

    if is_dir:
        return _run_tree_validation(options, tool_info)
    else:
        return _run_single_validation(options, tool_info)


def _run_single_validation(options: "RoundTripValidateOptions", tool_info) -> int:
    from .validation import _format
    from .workflow_tools import load_workflow

    workflow = load_workflow(options.workflow_path)
    if _format(workflow) != "native":
        print("Error: round-trip validation requires a native .ga workflow", file=sys.stderr)
        return 1

    result = roundtrip_validate(
        workflow,
        tool_info,
        workflow_path=options.workflow_path,
        strip_bookkeeping=options.strip_bookkeeping,
    )

    # Write intermediate artifacts if requested
    if options.output_format2 and result.format2_dict:
        _write_json(result.format2_dict, options.output_format2)
        print(f"Format2 written to {options.output_format2}", file=sys.stderr)

    if options.output_native and result.reimported_dict:
        _write_json(result.reimported_dict, options.output_native)
        print(f"Reimported native written to {options.output_native}", file=sys.stderr)

    print(format_validation_text([result], verbose=options.verbose))
    return 0 if result.ok else 1


def _run_tree_validation(options: "RoundTripValidateOptions", tool_info) -> int:
    from .validation import _format
    from .workflow_tree import (
        discover_workflows,
        load_workflow_safe,
    )

    workflows = discover_workflows(options.workflow_path, include_format2=False)
    results: List[RoundTripValidationResult] = []

    for info in workflows:
        wf_dict = load_workflow_safe(info)
        if wf_dict is None:
            results.append(
                RoundTripValidationResult(
                    workflow_path=info.path,
                    error="Failed to load workflow",
                )
            )
            continue

        if _format(wf_dict) != "native":
            continue

        result = roundtrip_validate(
            wf_dict,
            tool_info,
            workflow_path=info.relative_path,
            strip_bookkeeping=options.strip_bookkeeping,
        )
        results.append(result)

    print(format_validation_text(results, verbose=options.verbose))

    has_failures = any(not r.ok for r in results)
    return 1 if has_failures else 0


def _write_json(data: dict, path: str):
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    with open(path, "w") as f:
        json.dump(data, f, indent=4)
        f.write("\n")
