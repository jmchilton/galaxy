"""Stale state cleaning: domain logic, result types, formatters, and run() entry point.

Strips stale tool_state keys from native .ga workflows by comparing
keys against current tool input definitions.
"""

import argparse
import copy
import difflib
import json
import logging
import os
import sys
from dataclasses import (
    dataclass,
    field,
)
from typing import (
    Any,
    cast,
    Dict,
    List,
    Optional,
)

from pydantic import BaseModel

from galaxy.tool_util.parameters import (
    ConditionalParameterModel,
    RepeatParameterModel,
    ToolParameterT,
    validate_explicit_conditional_test_value,
)
from galaxy.tool_util_models import ParsedTool
from galaxy.tool_util_models.parameters import SectionParameterModel
from ._types import (
    GetToolInfo,
    NativeStepDict,
    NativeWorkflowDict,
)
from ._walker import (
    _NATIVE_BOOKKEEPING_KEYS,
    _test_value_matches_discriminator,
    as_dict,
    as_list,
)
from .validation_native import get_parsed_tool_for_native_step
from .workflow_tools import load_workflow

log = logging.getLogger(__name__)


# -- Options model --


class CleanOptions(BaseModel):
    workflow_path: str
    tool_source_cache_dir: Optional[str] = None
    verbose: bool = False
    populate_cache: bool = False
    tool_source: str = "auto"
    output_template: Optional[str] = None
    diff: bool = False
    report_json: Optional[str] = None
    report_markdown: Optional[str] = None

    @classmethod
    def from_namespace(cls, args: argparse.Namespace) -> "CleanOptions":
        fields = set(cls.model_fields)
        return cls(**{k: v for k, v in vars(args).items() if k in fields})


# -- Result types --


@dataclass
class StepCleanResult:
    step_index: str
    tool_id: str
    version: Optional[str]
    removed_keys: List[str] = field(default_factory=list)
    skipped: bool = False
    skip_reason: str = ""


@dataclass
class CleanResult:
    step_results: List[StepCleanResult] = field(default_factory=list)

    @property
    def total_removed(self) -> int:
        return sum(len(r.removed_keys) for r in self.step_results)

    @property
    def steps_with_removals(self) -> int:
        return sum(1 for r in self.step_results if r.removed_keys)

    def merge(self, other: "CleanResult"):
        self.step_results.extend(other.step_results)


@dataclass
class WorkflowCleanResult:
    path: str
    relative_path: str
    category: str
    step_results: List[StepCleanResult] = field(default_factory=list)
    total_removed: int = 0
    error: Optional[str] = None


@dataclass
class TreeCleanReport:
    root: str
    results: List[WorkflowCleanResult] = field(default_factory=list)

    @property
    def summary(self) -> Dict[str, int]:
        total_keys = sum(r.total_removed for r in self.results)
        affected = sum(1 for r in self.results if r.total_removed > 0)
        errors = sum(1 for r in self.results if r.error)
        clean = len(self.results) - affected - errors
        return {"total_keys": total_keys, "affected": affected, "clean": clean, "errors": errors}

    def by_category(self) -> Dict[str, List[WorkflowCleanResult]]:
        groups: Dict[str, List[WorkflowCleanResult]] = {}
        for r in self.results:
            cat = r.category or "(root)"
            groups.setdefault(cat, []).append(r)
        return groups


# -- Domain logic --


def _strip_recursive(
    state: Dict[str, Any],
    tool_inputs: List[ToolParameterT],
    removed_keys: List[str],
    prefix: str = "",
):
    """Remove stale keys from state dict in place.

    Works on the raw JSON-decoded dict (values are still JSON strings for leaves,
    JSON-encoded dicts/lists for containers). Only decodes container values when
    recursing into them. Mutates state in place to preserve key ordering.
    """
    known = {inp.name for inp in tool_inputs}

    stale = [key for key in state if key not in known and key not in _NATIVE_BOOKKEEPING_KEYS]
    for key in stale:
        path = f"{prefix}{key}" if prefix else key
        removed_keys.append(path)
        del state[key]

    for tool_input in tool_inputs:
        name = tool_input.name
        if name not in state:
            continue

        value = state[name]
        parameter_type = tool_input.parameter_type
        child_prefix = f"{prefix}{name}|" if prefix else f"{name}|"

        if parameter_type == "gx_conditional":
            conditional = cast(ConditionalParameterModel, tool_input)
            cond_state = as_dict(value)
            if cond_state is None:
                continue

            test_param = conditional.test_parameter
            test_value_raw = cond_state.get(test_param.name)
            test_value = validate_explicit_conditional_test_value(test_param.name, test_value_raw)

            target_when = None
            for when in conditional.whens:
                if test_value is None and when.is_default_when:
                    target_when = when
                elif test_value is not None and _test_value_matches_discriminator(test_value, when.discriminator):
                    target_when = when

            if target_when is None:
                recorded_case = cond_state.get("__current_case__")
                if isinstance(recorded_case, int) and 0 <= recorded_case < len(conditional.whens):
                    target_when = conditional.whens[recorded_case]

            if target_when is None:
                continue

            branch_inputs: List[ToolParameterT] = [test_param] + list(target_when.parameters)
            _strip_recursive(cond_state, branch_inputs, removed_keys, prefix=child_prefix)
            if isinstance(value, str):
                state[name] = json.dumps(cond_state)

        elif parameter_type == "gx_repeat":
            repeat = cast(RepeatParameterModel, tool_input)
            repeat_state = as_list(value)
            if not repeat_state:
                continue

            for i, instance in enumerate(repeat_state):
                if isinstance(instance, dict):
                    instance_prefix = f"{prefix}{name}_{i}|"
                    _strip_recursive(instance, list(repeat.parameters), removed_keys, prefix=instance_prefix)
            if isinstance(value, str):
                state[name] = json.dumps(repeat_state)

        elif parameter_type == "gx_section":
            section = cast(SectionParameterModel, tool_input)
            section_state = as_dict(value)
            if section_state is None:
                continue
            _strip_recursive(section_state, list(section.parameters), removed_keys, prefix=child_prefix)
            if isinstance(value, str):
                state[name] = json.dumps(section_state)


def strip_stale_keys(step: NativeStepDict, parsed_tool: ParsedTool) -> StepCleanResult:
    """Strip stale keys from a single step's tool_state."""
    tool_id = step.get("tool_id", "?")
    tool_version = step.get("tool_version")

    tool_state_str = step.get("tool_state")
    if not tool_state_str or not isinstance(tool_state_str, str):
        return StepCleanResult(
            step_index="?",
            tool_id=tool_id,
            version=tool_version,
            skipped=True,
            skip_reason="No tool_state",
        )

    tool_state = json.loads(tool_state_str)
    removed_keys: List[str] = []
    _strip_recursive(tool_state, list(parsed_tool.inputs), removed_keys)
    step["tool_state"] = json.dumps(tool_state)

    return StepCleanResult(
        step_index="?",
        tool_id=tool_id,
        version=tool_version,
        removed_keys=removed_keys,
    )


def clean_stale_state(workflow_dict: NativeWorkflowDict, get_tool_info: GetToolInfo, prefix: str = "") -> CleanResult:
    """Clean stale keys from all steps in a native workflow dict (mutates in place)."""
    result = CleanResult()
    steps = workflow_dict.get("steps", {})

    for step_index, step_def in sorted(steps.items(), key=lambda x: int(x[0])):
        step_label = f"{prefix}{step_index}" if prefix else str(step_index)

        if step_def.get("type") == "subworkflow" and "subworkflow" in step_def:
            sub_result = clean_stale_state(step_def["subworkflow"], get_tool_info, prefix=f"{step_label}.")
            result.merge(sub_result)
            continue

        tool_id = step_def.get("tool_id")
        if not tool_id:
            continue

        tool_state = step_def.get("tool_state")
        if not tool_state or not isinstance(tool_state, str):
            continue

        try:
            parsed_tool = get_parsed_tool_for_native_step(step_def, get_tool_info)
        except Exception as e:
            result.step_results.append(
                StepCleanResult(
                    step_index=step_label,
                    tool_id=tool_id,
                    version=step_def.get("tool_version"),
                    skipped=True,
                    skip_reason=f"No tool definition: {e}",
                )
            )
            continue

        if parsed_tool is None:
            result.step_results.append(
                StepCleanResult(
                    step_index=step_label,
                    tool_id=tool_id,
                    version=step_def.get("tool_version"),
                    skipped=True,
                    skip_reason="No tool definition",
                )
            )
            continue

        step_result = strip_stale_keys(step_def, parsed_tool)
        step_result.step_index = step_label
        result.step_results.append(step_result)

    return result


def expand_output_path(template: str, original_path: str) -> str:
    """Expand an output template with path specifiers.

    Specifiers: {path}, {dir}, {name}, {stem}, {ext}
    """
    path = os.path.abspath(original_path)
    dir_part = os.path.dirname(path)
    name = os.path.basename(path)
    stem, ext = os.path.splitext(name)
    return template.format(
        path=path,
        dir=dir_part,
        name=name,
        stem=stem,
        ext=ext,
    )


def clean_tree(
    root: str,
    get_tool_info: "GetToolInfo",
    output_template: Optional[str] = None,
) -> TreeCleanReport:
    """Clean stale state from all native .ga workflows under a directory tree.

    If output_template is None, operates in dry-run mode (no writes).
    """
    from .workflow_tree import (
        discover_workflows,
        load_workflow_safe,
    )

    workflows = discover_workflows(root, include_format2=False)
    report = TreeCleanReport(root=root)

    for info in workflows:
        wf_dict = load_workflow_safe(info)
        if wf_dict is None:
            report.results.append(
                WorkflowCleanResult(
                    path=info.path,
                    relative_path=info.relative_path,
                    category=info.category,
                    error="Failed to load workflow",
                )
            )
            continue

        if output_template is None:
            work_copy = copy.deepcopy(wf_dict)
        else:
            work_copy = wf_dict

        try:
            result = clean_stale_state(work_copy, get_tool_info)
        except Exception as e:
            report.results.append(
                WorkflowCleanResult(
                    path=info.path,
                    relative_path=info.relative_path,
                    category=info.category,
                    error=str(e),
                )
            )
            continue

        wf_result = WorkflowCleanResult(
            path=info.path,
            relative_path=info.relative_path,
            category=info.category,
            step_results=result.step_results,
            total_removed=result.total_removed,
        )
        report.results.append(wf_result)

        if result.total_removed > 0 and output_template is not None:
            output_json = json.dumps(work_copy, indent=4) + "\n"
            output_path = expand_output_path(output_template, info.path)
            os.makedirs(os.path.dirname(output_path), exist_ok=True)
            with open(output_path, "w") as f:
                f.write(output_json)

    return report


# -- Formatters --


def format_dry_run(result: CleanResult) -> str:
    lines = []
    for sr in result.step_results:
        if sr.skipped:
            lines.append(f"Step {sr.step_index} ({sr.tool_id}): SKIP ({sr.skip_reason})")
            continue
        if sr.removed_keys:
            tool_label = sr.tool_id
            if sr.version:
                tool_label += f" {sr.version}"
            lines.append(f"Step {sr.step_index} ({tool_label}):")
            lines.append(f"  Removed: {', '.join(sr.removed_keys)}")

    if result.total_removed:
        lines.append("---")
        lines.append(f"{result.total_removed} stale key(s) found across {result.steps_with_removals} step(s)")
    else:
        lines.append("No stale keys found.")
    return "\n".join(lines)


def format_tree_clean_text(report: TreeCleanReport) -> str:
    s = report.summary
    total_wf = len(report.results)
    lines = [
        f"Root: {report.root}",
        f"Workflows: {total_wf} | {s['total_keys']} stale key(s) across {s['affected']} workflow(s)",
        "",
    ]

    for r in report.results:
        if r.error:
            lines.append(f"  {r.relative_path}: ERROR ({r.error})")
            continue
        if r.total_removed > 0:
            lines.append(f"  {r.relative_path}: {r.total_removed} stale key(s)")
            for sr in r.step_results:
                if sr.removed_keys:
                    lines.append(f"    Step {sr.step_index} ({sr.tool_id}): {', '.join(sr.removed_keys)}")

    lines.append("---")
    lines.append(
        f"Summary: {s['total_keys']} stale key(s), {s['affected']} affected, {s['clean']} clean, {s['errors']} errors"
    )
    return "\n".join(lines)


def format_tree_clean_markdown(report: TreeCleanReport) -> str:
    s = report.summary
    total_wf = len(report.results)
    lines = [
        "# Stale State Cleaning Report",
        "",
        f"Root: `{report.root}`",
        f"Workflows: {total_wf} | {s['total_keys']} stale key(s) across {s['affected']} workflow(s)",
        "",
    ]

    affected = [r for r in report.results if r.total_removed > 0 or r.error]
    if affected:
        lines.append("## Affected Workflows")
        lines.append("")
        lines.append("| Workflow | Steps Affected | Keys Removed | Details |")
        lines.append("| --- | --- | --- | --- |")
        for r in affected:
            name = r.relative_path
            if r.error:
                lines.append(f"| {name} | - | - | ERROR: {r.error} |")
                continue
            steps_affected = sum(1 for sr in r.step_results if sr.removed_keys)
            details_parts = []
            for sr in r.step_results:
                if sr.removed_keys:
                    details_parts.append(f"Step {sr.step_index} ({sr.tool_id}): {', '.join(sr.removed_keys)}")
            detail = "; ".join(details_parts) if details_parts else ""
            lines.append(f"| {name} | {steps_affected} | {r.total_removed} | {detail} |")
        lines.append("")

    if s["clean"] > 0:
        lines.append(f"## Clean Workflows ({s['clean']})")
        lines.append("")
        lines.append("All other workflows have no stale keys.")
        lines.append("")

    detail_lines = []
    for r in report.results:
        if r.total_removed > 0:
            detail_lines.append(f"### {r.relative_path}")
            for sr in r.step_results:
                if sr.removed_keys:
                    tool_label = sr.tool_id
                    if sr.version:
                        tool_label += f" {sr.version}"
                    detail_lines.append(
                        f"- Step {sr.step_index} ({tool_label}): " f"Removed `{'`, `'.join(sr.removed_keys)}`"
                    )
            detail_lines.append("")

    if detail_lines:
        lines.append("## Per-Workflow Details")
        lines.append("")
        lines.extend(detail_lines)

    return "\n".join(lines)


def format_json_single(result: CleanResult, workflow_path: str) -> dict:
    return {
        "workflow": workflow_path,
        "total_removed": result.total_removed,
        "steps_with_removals": result.steps_with_removals,
        "results": [
            {
                "step": sr.step_index,
                "tool_id": sr.tool_id,
                "version": sr.version,
                "removed_keys": sr.removed_keys,
                "skipped": sr.skipped,
                "skip_reason": sr.skip_reason,
            }
            for sr in result.step_results
        ],
    }


def format_json_tree(report: TreeCleanReport) -> dict:
    return {
        "root": report.root,
        "workflows": [
            {
                "path": r.relative_path,
                "category": r.category,
                "error": r.error,
                "total_removed": r.total_removed,
                "results": (
                    [
                        {
                            "step": sr.step_index,
                            "tool_id": sr.tool_id,
                            "version": sr.version,
                            "removed_keys": sr.removed_keys,
                            "skipped": sr.skipped,
                            "skip_reason": sr.skip_reason,
                        }
                        for sr in r.step_results
                    ]
                    if not r.error
                    else []
                ),
            }
            for r in report.results
        ],
        "summary": report.summary,
    }


# -- Output helpers --


def _write_output(content: str, dest: Optional[str]):
    if dest is None or dest == "-":
        print(content)
    else:
        with open(dest, "w") as f:
            f.write(content)
        print(f"Report written to {dest}", file=sys.stderr)


def _all_reports_to_files(options: CleanOptions) -> bool:
    """True if all --report-* flags point to files (none writing to stdout)."""
    for dest in [options.report_json, options.report_markdown]:
        if dest is not None and dest == "-":
            return False
    return True


# -- Entry point --


def run_clean(options: CleanOptions) -> int:
    """Run clean pipeline. Returns exit code."""
    from ._cli_common import setup_logging
    from .cache import (
        build_tool_info,
        populate_cache,
    )

    setup_logging(options.verbose)
    tool_info = build_tool_info(options.tool_source_cache_dir)

    if options.populate_cache:
        populate_cache(tool_info, options.workflow_path, source=options.tool_source)
        print()

    is_dir = os.path.isdir(options.workflow_path)

    if is_dir:
        return _run_tree(options, tool_info)
    else:
        return _run_single(options, tool_info)


def _run_single(options: CleanOptions, tool_info) -> int:
    workflow = load_workflow(options.workflow_path)
    original_json = json.dumps(workflow, indent=4) + "\n"

    dry_run = options.output_template is None

    if dry_run:
        work_copy = copy.deepcopy(workflow)
    else:
        work_copy = workflow

    result = clean_stale_state(work_copy, tool_info)

    if options.diff:
        cleaned_json = json.dumps(work_copy, indent=4) + "\n"
        diff = difflib.unified_diff(
            original_json.splitlines(keepends=True),
            cleaned_json.splitlines(keepends=True),
            fromfile=options.workflow_path,
            tofile=options.workflow_path + " (cleaned)",
        )
        diff_text = "".join(diff)
        if diff_text:
            print(diff_text, end="")
        else:
            print("No changes.")

    has_explicit_report = options.report_json is not None or options.report_markdown is not None

    if options.report_json is not None:
        data = format_json_single(result, options.workflow_path)
        _write_output(json.dumps(data, indent=2), options.report_json)

    if options.report_markdown is not None:
        tree_report = TreeCleanReport(root=options.workflow_path)
        tree_report.results.append(
            WorkflowCleanResult(
                path=options.workflow_path,
                relative_path=os.path.basename(options.workflow_path),
                category="",
                step_results=result.step_results,
                total_removed=result.total_removed,
            )
        )
        _write_output(format_tree_clean_markdown(tree_report), options.report_markdown)

    if not has_explicit_report and not options.diff:
        print(format_dry_run(result))
    elif _all_reports_to_files(options) and not options.diff:
        print(format_dry_run(result), file=sys.stderr)

    if not dry_run and result.total_removed > 0:
        output_json = json.dumps(work_copy, indent=4) + "\n"
        output_path = expand_output_path(options.output_template, options.workflow_path)
        os.makedirs(os.path.dirname(os.path.abspath(output_path)), exist_ok=True)
        with open(output_path, "w") as f:
            f.write(output_json)

    return 1 if result.total_removed else 0


def _run_tree(options: CleanOptions, tool_info) -> int:
    report = clean_tree(options.workflow_path, tool_info, output_template=options.output_template)

    has_explicit_report = options.report_json is not None or options.report_markdown is not None

    if options.report_json is not None:
        data = format_json_tree(report)
        _write_output(json.dumps(data, indent=2), options.report_json)

    if options.report_markdown is not None:
        _write_output(format_tree_clean_markdown(report), options.report_markdown)

    if not has_explicit_report:
        print(format_tree_clean_text(report))
    elif _all_reports_to_files(options):
        s = report.summary
        print(f"Summary: {s['total_keys']} stale key(s), {s['affected']} affected", file=sys.stderr)

    s = report.summary
    if s["total_keys"] > 0 or s["errors"] > 0:
        return 1
    return 0
