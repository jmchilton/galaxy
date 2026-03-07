"""Round-trip test harness for workflow state conversion.

Tests native→format2→native and format2→native→format2 round-trips,
cataloging failures by class to drive conversion library work.
"""

import json
import os
import traceback
from dataclasses import dataclass, field
from enum import Enum
from typing import (
    Any,
    Dict,
    List,
    Optional,
    Tuple,
)

import pytest
from gxformat2.converter import python_to_workflow
from gxformat2.export import from_galaxy_native
from gxformat2.yaml import ordered_load

from galaxy.tool_util.workflow_state.convert import (
    convert_state_to_format2,
    ConversionValidationFailure,
    Format2State,
)
from galaxy.tool_util.workflow_state._types import GetToolInfo
from galaxy.util import galaxy_directory
from galaxy.workflow.gx_validator import GET_TOOL_INFO


# -- Paths --

TEST_WORKFLOW_DIRECTORY = os.path.join(galaxy_directory(), "lib", "galaxy_test", "workflow")
TEST_BASE_DATA_DIRECTORY = os.path.join(galaxy_directory(), "lib", "galaxy_test", "base", "data")
SCRIPT_DIRECTORY = os.path.abspath(os.path.dirname(__file__))


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
    diffs: List[str] = field(default_factory=list)


@dataclass
class RoundTripResult:
    workflow_name: str
    direction: str  # "native_to_format2" or "format2_to_native"
    step_results: List[StepResult] = field(default_factory=list)

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
            parts.append(f"step {f.step_id} ({f.tool_id}): {f.failure_class.value if f.failure_class else 'unknown'} - {f.error}")
        return "; ".join(parts)


# -- Comparison logic --

SKIP_KEYS = {"__current_case__", "__page__", "__rerun_remap_job_id__", "__index__", "__job_resource", "chromInfo"}


def compare_tool_state(orig: dict, after: dict, path: str = "") -> List[str]:
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
            # New key in roundtripped — only a diff if it has a meaningful value
            if after_val not in (None, "null"):
                diffs.append(f"{key_path}: missing in original, present in roundtripped ({after_val!r})")
        elif key not in after:
            # Missing in roundtripped — null/None/RuntimeValue/ConnectedValue/empty are expected to be stripped
            if orig_val not in (None, "null", []) and not _is_connection_marker(orig_val):
                diffs.append(f"{key_path}: present in original ({orig_val!r}), missing in roundtripped")
        elif isinstance(orig_val, dict) and isinstance(after_val, dict):
            diffs.extend(compare_tool_state(orig_val, after_val, key_path))
        elif isinstance(orig_val, list) and isinstance(after_val, list):
            diffs.extend(_compare_list_state(orig_val, after_val, key_path))
        elif not _values_equivalent(orig_val, after_val):
            diffs.append(f"{key_path}: {orig_val!r} != {after_val!r}")
    return diffs


def _compare_list_state(orig: list, after: list, path: str) -> List[str]:
    """Compare lists (e.g. repeat instances) in tool state."""
    diffs = []
    # Parse JSON strings if needed
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
    # String-to-int coercion
    try:
        if isinstance(a, str) and isinstance(b, int):
            return int(a) == b
        if isinstance(a, int) and isinstance(b, str):
            return a == int(b)
    except (ValueError, TypeError):
        pass
    # String-to-float coercion
    try:
        if isinstance(a, str) and isinstance(b, float):
            return float(a) == b
        if isinstance(a, float) and isinstance(b, str):
            return a == float(b)
    except (ValueError, TypeError):
        pass
    # String-to-bool coercion
    if isinstance(a, str) and isinstance(b, bool):
        return a.lower() in ("true", "yes") and b or a.lower() in ("false", "no") and not b
    if isinstance(a, bool) and isinstance(b, str):
        return _values_equivalent(b, a)
    # null/None equivalence
    if a == "null" and b is None:
        return True
    if a is None and b == "null":
        return True
    return False


def compare_connections(orig_connections: dict, after_connections: dict, path: str = "") -> List[str]:
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
            # Normalize to lists
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


def compare_steps(orig_step: dict, after_step: dict) -> List[str]:
    """Compare two native workflow steps for functional equivalence."""
    diffs = []
    # tool_id / tool_version
    for key in ["tool_id", "tool_version"]:
        if orig_step.get(key) != after_step.get(key):
            diffs.append(f"{key}: {orig_step.get(key)!r} != {after_step.get(key)!r}")

    # tool_state comparison
    orig_ts = orig_step.get("tool_state")
    after_ts = after_step.get("tool_state")
    if orig_ts and after_ts:
        orig_parsed = json.loads(orig_ts) if isinstance(orig_ts, str) else orig_ts
        after_parsed = json.loads(after_ts) if isinstance(after_ts, str) else after_ts
        diffs.extend(compare_tool_state(orig_parsed, after_parsed))

    # input_connections comparison
    orig_ic = orig_step.get("input_connections", {})
    after_ic = after_step.get("input_connections", {})
    diffs.extend(compare_connections(orig_ic, after_ic))

    return diffs


# -- Loaders --


def _load(path: str) -> dict:
    with open(path) as f:
        return ordered_load(f)


def load_native_workflow(filename: str) -> dict:
    return _load(os.path.join(TEST_BASE_DATA_DIRECTORY, filename))


def load_framework_workflow(name: str) -> dict:
    return _load(os.path.join(TEST_WORKFLOW_DIRECTORY, f"{name}.gxwf.yml"))


def load_unit_workflow(name: str) -> dict:
    return _load(os.path.join(SCRIPT_DIRECTORY, f"{name}.gxwf.yml"))


# -- Round-trip functions --


def classify_error(e: Exception) -> FailureClass:
    msg = str(e)
    tb = traceback.format_exc()
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


def roundtrip_native_step(
    step: dict,
    step_id: str,
    get_tool_info: GetToolInfo,
) -> StepResult:
    """Try to convert a single native step to format2 state."""
    tool_id = step.get("tool_id")
    step_type = step.get("type", "tool")

    if step_type != "tool" or not tool_id:
        return StepResult(step_id=step_id, tool_id=tool_id, success=True)

    if step_type == "subworkflow":
        return StepResult(
            step_id=step_id, tool_id=tool_id, success=False,
            failure_class=FailureClass.SUBWORKFLOW, error="Subworkflows not yet supported",
        )

    try:
        format2_state = convert_state_to_format2(step, get_tool_info)
        return StepResult(step_id=step_id, tool_id=tool_id, success=True)
    except Exception as e:
        return StepResult(
            step_id=step_id, tool_id=tool_id, success=False,
            failure_class=classify_error(e), error=str(e),
        )


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


def full_roundtrip_native(
    workflow_dict: dict,
    get_tool_info: GetToolInfo,
    workflow_name: str = "",
) -> Tuple[RoundTripResult, Optional[List[str]]]:
    """Full round-trip: native → format2 → native' → compare.

    First tries per-step conversion. If all steps convert successfully,
    builds a format2 workflow and converts back to native for comparison.
    """
    import copy

    step_result = roundtrip_native_workflow(workflow_dict, get_tool_info, workflow_name)
    if not step_result.success:
        return step_result, None

    # Build format2 workflow with state blocks
    # Use gxformat2's from_galaxy_native as the structural base
    native_copy = copy.deepcopy(workflow_dict)
    # Ensure steps have required fields for gxformat2 export
    for step in native_copy.get("steps", {}).values():
        step.setdefault("label", None)
        step.setdefault("annotation", "")
    format2_dict = from_galaxy_native(native_copy)

    # Replace tool_state with state for each tool step
    format2_steps = format2_dict.get("steps", [])
    if isinstance(format2_steps, list):
        steps_iter = enumerate(format2_steps)
    else:
        steps_iter = format2_steps.items()

    # Count input steps to compute offset (format2 inputs are in 'inputs' dict, not 'steps')
    num_inputs = len(format2_dict.get("inputs", {}))

    for step_key, format2_step in steps_iter:
        if format2_step.get("tool_id") or "tool_state" in format2_step:
            # Map format2 step index to native step id
            native_step_id = step_key + num_inputs if isinstance(step_key, int) else step_key
            native_step = _find_matching_native_step(workflow_dict, format2_step, native_step_id)
            if native_step:
                try:
                    f2_state = convert_state_to_format2(native_step, get_tool_info)
                    # Replace tool_state with state
                    format2_step.pop("tool_state", None)
                    format2_step["state"] = f2_state.state
                    # Merge connections from format2 in dict
                    # (connections already handled by from_galaxy_native's in dict)
                except ConversionValidationFailure:
                    pass  # Keep tool_state as-is

    # Convert back to native via gxformat2
    try:
        native_prime = python_to_workflow(copy.deepcopy(format2_dict), galaxy_interface=None)
    except Exception as e:
        step_result.step_results.append(StepResult(
            step_id="reimport", tool_id=None, success=False,
            failure_class=FailureClass.REIMPORT_ERROR, error=str(e),
        ))
        return step_result, None

    # Compare each tool step
    all_diffs = []
    for step_id, orig_step in workflow_dict["steps"].items():
        if orig_step.get("type") not in ("tool",):
            continue
        after_step = native_prime.get("steps", {}).get(step_id)
        if after_step is None:
            all_diffs.append(f"step {step_id}: missing in roundtripped workflow")
            continue
        diffs = compare_steps(orig_step, after_step)
        all_diffs.extend([f"step {step_id}: {d}" for d in diffs])

    return step_result, all_diffs


def _find_matching_native_step(native_workflow: dict, format2_step: dict, format2_index: int) -> Optional[dict]:
    """Find the native step matching a format2 step by position."""
    # Match by step index — format2 steps are ordered to correspond to native step indices
    # The format2 steps list includes input steps, so format2_index maps to the native step id
    step_id = str(format2_index)
    native_steps = native_workflow.get("steps", {})
    if step_id in native_steps:
        return native_steps[step_id]
    # Fallback: try matching by label then tool_id
    tool_id = format2_step.get("tool_id")
    label = format2_step.get("label")
    for step in native_steps.values():
        if label and step.get("label") == label and step.get("tool_id") == tool_id:
            return step
    for step in native_steps.values():
        if step.get("tool_id") == tool_id:
            return step
    return None


# -- Test inventory --

NATIVE_WORKFLOWS = [
    "test_workflow_1.ga",
    "test_workflow_2.ga",
    "test_workflow_two_random_lines.ga",
    "test_workflow_pause.ga",
    "test_workflow_batch.ga",
    "test_workflow_matching_lists.ga",
    "test_workflow_randomlines_legacy_params.ga",
    "test_workflow_randomlines_legacy_params_mixed_types.ga",
    "test_workflow_topoambigouity.ga",
    "test_workflow_topoambigouity_auto_laidout.ga",
    "test_workflow_map_reduce_pause.ga",
    "test_workflow_missing_tool.ga",
    "test_workflow_validation_1.ga",
    "test_workflow_with_input_tags.ga",
    "test_workflow_with_runtime_input.ga",
]

FRAMEWORK_WORKFLOWS = [
    "default_values",
    "default_values_optional",
    "directory_index",
    "empty_collection_sort",
    "filter_null",
    "flat_over_paired_or_unpaired",
    "flatten_collection",
    "flatten_collection_over_execution",
    "integer_into_data_column",
    "map_over_expression",
    "multi_select_mapping",
    "multiple_integer_into_data_column",
    "multiple_text",
    "multiple_versions",
    "optional_conditional_inputs_to_build_list",
    "optional_text_param_rescheduling",
    "output_parameter",
    "rename_based_on_input_collection",
    "replacement_parameters_legacy",
    "replacement_parameters_nested",
    "replacement_parameters_text",
    "subcollection_rank_sorting",
    "subcollection_rank_sorting_paired",
    "triply_nested_list_mapping",
    "zip_collection",
]

UNIT_WORKFLOWS = [
    "valid/simple_data",
    "valid/simple_int",
]


# -- Sweep function --


def run_sweep(get_tool_info: Optional[GetToolInfo] = None) -> Dict[str, RoundTripResult]:
    """Run round-trip conversion sweep across all test workflows."""
    if get_tool_info is None:
        get_tool_info = GET_TOOL_INFO

    results: Dict[str, RoundTripResult] = {}

    # Native workflows
    for filename in NATIVE_WORKFLOWS:
        path = os.path.join(TEST_BASE_DATA_DIRECTORY, filename)
        if not os.path.exists(path):
            continue
        try:
            workflow = load_native_workflow(filename)
            result = roundtrip_native_workflow(workflow, get_tool_info, filename)
        except Exception as e:
            result = RoundTripResult(
                workflow_name=filename, direction="native_to_format2",
                step_results=[StepResult(
                    step_id="load", tool_id=None, success=False,
                    failure_class=classify_error(e), error=str(e),
                )],
            )
        results[f"native/{filename}"] = result

    # Framework format2 workflows (validate format2→native→format2)
    for name in FRAMEWORK_WORKFLOWS:
        path = os.path.join(TEST_WORKFLOW_DIRECTORY, f"{name}.gxwf.yml")
        if not os.path.exists(path):
            continue
        try:
            workflow = load_framework_workflow(name)
            # Convert to native first, then try round-tripping back
            native = python_to_workflow(workflow, galaxy_interface=None)
            result = roundtrip_native_workflow(native, get_tool_info, name)
            result.direction = "format2_to_native_to_format2"
        except Exception as e:
            result = RoundTripResult(
                workflow_name=name, direction="format2_to_native_to_format2",
                step_results=[StepResult(
                    step_id="convert", tool_id=None, success=False,
                    failure_class=classify_error(e), error=str(e),
                )],
            )
        results[f"format2/{name}"] = result

    # Unit test workflows
    for name in UNIT_WORKFLOWS:
        try:
            workflow = load_unit_workflow(name)
            native = python_to_workflow(workflow, galaxy_interface=None)
            result = roundtrip_native_workflow(native, get_tool_info, name)
            result.direction = "format2_to_native_to_format2"
        except Exception as e:
            result = RoundTripResult(
                workflow_name=name, direction="format2_to_native_to_format2",
                step_results=[StepResult(
                    step_id="convert", tool_id=None, success=False,
                    failure_class=classify_error(e), error=str(e),
                )],
            )
        results[f"unit/{name}"] = result

    return results


def print_sweep_results(results: Dict[str, RoundTripResult]):
    """Print a summary table of sweep results."""
    print(f"\n{'='*80}")
    print(f"Round-Trip Sweep Results")
    print(f"{'='*80}\n")

    passes = []
    failures = []
    for name, result in sorted(results.items()):
        if result.success:
            passes.append(name)
        else:
            failures.append((name, result))

    print(f"PASSED: {len(passes)}/{len(results)}")
    for name in passes:
        print(f"  [PASS] {name}")

    print(f"\nFAILED: {len(failures)}/{len(results)}")

    # Group by failure class
    by_class: Dict[str, List[Tuple[str, str]]] = {}
    for name, result in failures:
        for sr in result.step_results:
            if not sr.success:
                fc = sr.failure_class.value if sr.failure_class else "unknown"
                by_class.setdefault(fc, []).append((name, f"step {sr.step_id} ({sr.tool_id}): {sr.error}"))

    for fc, items in sorted(by_class.items()):
        print(f"\n  [{fc}] ({len(items)} failures)")
        for name, detail in items:
            print(f"    {name}: {detail}")

    print(f"\n{'='*80}")


@dataclass
class FullRoundTripResult:
    workflow_name: str
    conversion_success: bool
    diffs: Optional[List[str]] = None
    error: Optional[str] = None

    @property
    def success(self) -> bool:
        return self.conversion_success and self.diffs is not None and len(self.diffs) == 0


def run_full_roundtrip_sweep(get_tool_info: Optional[GetToolInfo] = None) -> Dict[str, FullRoundTripResult]:
    """Run full native→format2→native'→compare for all native workflows."""
    if get_tool_info is None:
        get_tool_info = GET_TOOL_INFO

    results: Dict[str, FullRoundTripResult] = {}

    for filename in NATIVE_WORKFLOWS:
        path = os.path.join(TEST_BASE_DATA_DIRECTORY, filename)
        if not os.path.exists(path):
            continue
        try:
            workflow = load_native_workflow(filename)
            step_result, diffs = full_roundtrip_native(workflow, get_tool_info, filename)
            if not step_result.success:
                failures = [r for r in step_result.step_results if not r.success]
                error = "; ".join(f"step {f.step_id}: {f.error}" for f in failures)
                results[filename] = FullRoundTripResult(
                    workflow_name=filename, conversion_success=False, error=error,
                )
            else:
                results[filename] = FullRoundTripResult(
                    workflow_name=filename, conversion_success=True, diffs=diffs,
                )
        except Exception as e:
            results[filename] = FullRoundTripResult(
                workflow_name=filename, conversion_success=False, error=str(e),
            )

    return results


def print_full_roundtrip_results(results: Dict[str, FullRoundTripResult]):
    print(f"\n{'='*80}")
    print(f"Full Round-Trip Sweep (native → format2 → native' → compare)")
    print(f"{'='*80}\n")

    passes = []
    conversion_failures = []
    diff_failures = []
    for name, result in sorted(results.items()):
        if result.success:
            passes.append(name)
        elif not result.conversion_success:
            conversion_failures.append((name, result))
        else:
            diff_failures.append((name, result))

    print(f"PASSED: {len(passes)}/{len(results)}")
    for name in passes:
        print(f"  [PASS] {name}")

    if conversion_failures:
        print(f"\nCONVERSION FAILURES: {len(conversion_failures)}")
        for name, result in conversion_failures:
            print(f"  [CONV] {name}: {result.error}")

    if diff_failures:
        print(f"\nDIFF FAILURES: {len(diff_failures)}")
        for name, result in diff_failures:
            print(f"  [DIFF] {name}:")
            for d in (result.diffs or []):
                print(f"    {d}")

    print(f"\n{'='*80}")


# -- Pytest tests --


class TestRoundTripSweep:
    """Run the sweep and report. This is the main entry point for cataloging failures."""

    def test_sweep_report(self):
        """Run per-step conversion sweep. Does NOT assert all pass - this is diagnostic."""
        results = run_sweep()
        print_sweep_results(results)
        self._results = results

    def test_full_roundtrip_sweep(self):
        """Run full native→format2→native'→compare sweep for native workflows."""
        results = run_full_roundtrip_sweep()
        print_full_roundtrip_results(results)
        self._full_results = results


class TestNativeRoundTrip:
    """Test round-trip for native workflows that we expect to work."""

    def test_workflow_two_random_lines(self):
        workflow = load_native_workflow("test_workflow_two_random_lines.ga")
        result = roundtrip_native_workflow(workflow, GET_TOOL_INFO, "test_workflow_two_random_lines.ga")
        _assert_roundtrip_passes(result)

    def test_workflow_1(self):
        workflow = load_native_workflow("test_workflow_1.ga")
        result = roundtrip_native_workflow(workflow, GET_TOOL_INFO, "test_workflow_1.ga")
        _assert_roundtrip_passes(result)


class TestFullNativeRoundTrip:
    """Full round-trip: native → format2 → native' → compare."""

    def test_workflow_1(self):
        workflow = load_native_workflow("test_workflow_1.ga")
        result, diffs = full_roundtrip_native(workflow, GET_TOOL_INFO, "test_workflow_1.ga")
        _assert_roundtrip_passes(result)
        _assert_no_diffs(diffs, "test_workflow_1.ga")

    def test_workflow_two_random_lines(self):
        workflow = load_native_workflow("test_workflow_two_random_lines.ga")
        result, diffs = full_roundtrip_native(workflow, GET_TOOL_INFO, "test_workflow_two_random_lines.ga")
        _assert_roundtrip_passes(result)
        _assert_no_diffs(diffs, "test_workflow_two_random_lines.ga")

    def test_workflow_batch(self):
        workflow = load_native_workflow("test_workflow_batch.ga")
        result, diffs = full_roundtrip_native(workflow, GET_TOOL_INFO, "test_workflow_batch.ga")
        _assert_roundtrip_passes(result)
        _assert_no_diffs(diffs, "test_workflow_batch.ga")

    def test_workflow_pause(self):
        workflow = load_native_workflow("test_workflow_pause.ga")
        result, diffs = full_roundtrip_native(workflow, GET_TOOL_INFO, "test_workflow_pause.ga")
        _assert_roundtrip_passes(result)
        _assert_no_diffs(diffs, "test_workflow_pause.ga")


class TestFormat2RoundTrip:
    """Test round-trip for format2 workflows that we expect to work."""

    def test_simple_int(self):
        workflow = load_unit_workflow("valid/simple_int")
        native = python_to_workflow(workflow, galaxy_interface=None)
        result = roundtrip_native_workflow(native, GET_TOOL_INFO, "simple_int")
        _assert_roundtrip_passes(result)

    def test_simple_data(self):
        workflow = load_unit_workflow("valid/simple_data")
        native = python_to_workflow(workflow, galaxy_interface=None)
        result = roundtrip_native_workflow(native, GET_TOOL_INFO, "simple_data")
        _assert_roundtrip_passes(result)


class TestComparison:
    """Test the comparison logic itself."""

    def test_skip_bookkeeping_keys(self):
        orig = {"param": "5", "__current_case__": 0, "__page__": 0}
        after = {"param": 5}
        diffs = compare_tool_state(orig, after)
        assert len(diffs) == 0

    def test_type_coercion(self):
        assert _values_equivalent("5", 5)
        assert _values_equivalent(5, "5")
        assert _values_equivalent("3.14", 3.14)
        assert _values_equivalent("null", None)
        assert _values_equivalent(None, "null")
        assert not _values_equivalent("5", 6)

    def test_nested_comparison(self):
        orig = {"cond": {"selector": "a", "__current_case__": 0, "param": "1"}}
        after = {"cond": {"selector": "a", "param": 1}}
        diffs = compare_tool_state(orig, after)
        assert len(diffs) == 0

    def test_detects_mismatch(self):
        orig = {"param": "hello"}
        after = {"param": "world"}
        diffs = compare_tool_state(orig, after)
        assert len(diffs) == 1
        assert "param" in diffs[0]


def _assert_roundtrip_passes(result: RoundTripResult):
    failures = [r for r in result.step_results if not r.success]
    if failures:
        details = "\n".join(
            f"  step {f.step_id} ({f.tool_id}): [{f.failure_class}] {f.error}"
            for f in failures
        )
        pytest.fail(f"Round-trip failed for {result.workflow_name}:\n{details}")


def _assert_no_diffs(diffs: Optional[List[str]], workflow_name: str):
    if diffs is None:
        pytest.fail(f"Full round-trip for {workflow_name} did not produce comparison (conversion failed)")
    if diffs:
        details = "\n".join(f"  {d}" for d in diffs)
        pytest.fail(f"Round-trip diffs for {workflow_name}:\n{details}")


# -- CLI entry point --

if __name__ == "__main__":
    results = run_sweep()
    print_sweep_results(results)
