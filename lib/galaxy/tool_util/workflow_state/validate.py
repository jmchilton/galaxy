"""Workflow validation: domain logic, result types, formatters, and run() entry point.

Validates a workflow's tool_state against tool definitions.
Supports both native .ga and format2 .gxwf.yml workflows.
"""

import argparse
import json
import logging
import os
import sys
from dataclasses import (
    dataclass,
    field,
)
from typing import (
    Dict,
    List,
    Literal,
    Optional,
)

from pydantic import BaseModel

from ._types import GetToolInfo
from .validation import _format
from .validation_format2 import validate_step_format2
from .validation_native import (
    get_parsed_tool_for_native_step,
    validate_native_step_against,
)
from .workflow_tools import load_workflow

log = logging.getLogger(__name__)

StepStatus = Literal["ok", "fail", "skip"]


# -- Options model --


class ValidateOptions(BaseModel):
    workflow_path: str
    tool_source_cache_dir: Optional[str] = None
    verbose: bool = False
    populate_cache: bool = False
    tool_source: str = "auto"
    strict: bool = False
    summary: bool = False
    report_json: Optional[str] = None
    report_markdown: Optional[str] = None

    @classmethod
    def from_namespace(cls, args: argparse.Namespace) -> "ValidateOptions":
        fields = set(cls.model_fields)
        return cls(**{k: v for k, v in vars(args).items() if k in fields})


# -- Result types --


@dataclass
class StepResult:
    step: str
    tool_id: Optional[str]
    version: Optional[str]
    status: StepStatus
    errors: List[str] = field(default_factory=list)


@dataclass
class WorkflowValidationResult:
    path: str
    relative_path: str
    category: str
    step_results: List[StepResult] = field(default_factory=list)
    error: Optional[str] = None


@dataclass
class TreeValidationReport:
    root: str
    results: List[WorkflowValidationResult] = field(default_factory=list)

    @property
    def summary(self) -> Dict[str, int]:
        ok = fail = skip = error = 0
        for r in self.results:
            if r.error:
                error += 1
                continue
            for sr in r.step_results:
                if sr.status == "ok":
                    ok += 1
                elif sr.status == "fail":
                    fail += 1
                elif sr.status == "skip":
                    skip += 1
        return {"ok": ok, "fail": fail, "skip": skip, "error": error}

    def by_category(self) -> Dict[str, List[WorkflowValidationResult]]:
        groups: Dict[str, List[WorkflowValidationResult]] = {}
        for r in self.results:
            cat = r.category or "(root)"
            groups.setdefault(cat, []).append(r)
        return groups


# -- Domain logic --


def validate_workflow_cli(workflow_dict: dict, get_tool_info: GetToolInfo) -> List[StepResult]:
    """Validate all steps in a workflow, collecting per-step results."""
    fmt = _format(workflow_dict)
    if fmt == "native":
        return _validate_native(workflow_dict, get_tool_info)
    else:
        return _validate_format2(workflow_dict, get_tool_info)


def _validate_native(workflow_dict: dict, get_tool_info: GetToolInfo, prefix: str = "") -> List[StepResult]:
    results = []
    steps = workflow_dict.get("steps", {})
    for step_index, step_def in sorted(steps.items(), key=lambda x: int(x[0])):
        step_label = f"{prefix}{step_index}" if prefix else str(step_index)

        if step_def.get("type") == "subworkflow" and "subworkflow" in step_def:
            sub_results = _validate_native(step_def["subworkflow"], get_tool_info, prefix=f"{step_label}.")
            results.extend(sub_results)
            continue

        tool_id = step_def.get("tool_id")
        tool_version = step_def.get("tool_version")

        if not tool_id:
            continue

        tool_state = step_def.get("tool_state")
        if not tool_state or not isinstance(tool_state, str):
            results.append(
                StepResult(
                    step=step_label,
                    tool_id=tool_id,
                    version=tool_version,
                    status="skip",
                    errors=["No tool_state found"],
                )
            )
            continue

        try:
            parsed_tool = get_parsed_tool_for_native_step(step_def, get_tool_info)
        except Exception as e:
            results.append(
                StepResult(
                    step=step_label,
                    tool_id=tool_id,
                    version=tool_version,
                    status="skip",
                    errors=[f"No tool definition: {e}"],
                )
            )
            continue

        if parsed_tool is None:
            results.append(
                StepResult(
                    step=step_label,
                    tool_id=tool_id,
                    version=tool_version,
                    status="skip",
                    errors=["No tool definition"],
                )
            )
            continue

        try:
            validate_native_step_against(step_def, parsed_tool)
            results.append(
                StepResult(
                    step=step_label,
                    tool_id=tool_id,
                    version=tool_version,
                    status="ok",
                )
            )
        except Exception as e:
            results.append(
                StepResult(
                    step=step_label,
                    tool_id=tool_id,
                    version=tool_version,
                    status="fail",
                    errors=[str(e)],
                )
            )

    return results


def _validate_format2(workflow_dict: dict, get_tool_info: GetToolInfo, prefix: str = "") -> List[StepResult]:
    from gxformat2.model import (
        get_native_step_type,
        steps_as_list,
    )

    results = []
    steps = steps_as_list(workflow_dict)
    for i, step_dict in enumerate(steps):
        step_label = f"{prefix}{i}" if prefix else str(i)
        step_type = get_native_step_type(step_dict)

        if step_type == "subworkflow":
            run = step_dict.get("run")
            if isinstance(run, dict):
                sub_results = _validate_format2(run, get_tool_info, prefix=f"{step_label}.")
                results.extend(sub_results)
            continue

        if step_type != "tool":
            continue

        tool_id = step_dict.get("tool_id")
        tool_version = step_dict.get("tool_version")

        if not tool_id:
            continue

        try:
            validate_step_format2(step_dict, get_tool_info)
            results.append(
                StepResult(
                    step=step_label,
                    tool_id=tool_id,
                    version=tool_version,
                    status="ok",
                )
            )
        except Exception as e:
            error_str = str(e)
            if "No tool definition" in error_str or "Not a toolshed tool" in error_str:
                results.append(
                    StepResult(
                        step=step_label,
                        tool_id=tool_id,
                        version=tool_version,
                        status="skip",
                        errors=[error_str],
                    )
                )
            else:
                results.append(
                    StepResult(
                        step=step_label,
                        tool_id=tool_id,
                        version=tool_version,
                        status="fail",
                        errors=[error_str],
                    )
                )

    return results


def validate_tree(root: str, get_tool_info: GetToolInfo) -> TreeValidationReport:
    """Validate all workflows under a directory tree."""
    from .workflow_tree import (
        discover_workflows,
        load_workflow_safe,
    )

    workflows = discover_workflows(root)
    report = TreeValidationReport(root=root)

    for info in workflows:
        wf_dict = load_workflow_safe(info)
        if wf_dict is None:
            report.results.append(
                WorkflowValidationResult(
                    path=info.path,
                    relative_path=info.relative_path,
                    category=info.category,
                    error="Failed to load workflow",
                )
            )
            continue

        try:
            step_results = validate_workflow_cli(wf_dict, get_tool_info)
        except Exception as e:
            report.results.append(
                WorkflowValidationResult(
                    path=info.path,
                    relative_path=info.relative_path,
                    category=info.category,
                    error=str(e),
                )
            )
            continue

        report.results.append(
            WorkflowValidationResult(
                path=info.path,
                relative_path=info.relative_path,
                category=info.category,
                step_results=step_results,
            )
        )

    return report


# -- Formatters --


def format_text(results: List[StepResult], summary_only: bool = False) -> str:
    lines = []
    ok = sum(1 for r in results if r.status == "ok")
    fail = sum(1 for r in results if r.status == "fail")
    skip = sum(1 for r in results if r.status == "skip")

    if not summary_only:
        for r in results:
            tool_label = r.tool_id or "?"
            if r.version:
                tool_label += f" ({r.version})"

            if r.status == "ok":
                lines.append(f"Step {r.step}: {tool_label} ... OK")
            elif r.status == "fail":
                lines.append(f"Step {r.step}: {tool_label} ... FAIL")
                for err in r.errors:
                    lines.append(f"  {err}")
            elif r.status == "skip":
                reason = r.errors[0] if r.errors else "skipped"
                lines.append(f"Step {r.step}: {tool_label} ... SKIP ({reason})")

        lines.append("---")

    lines.append(f"Summary: {ok} OK, {fail} FAIL, {skip} SKIP")
    return "\n".join(lines)


def format_tree_text(report: TreeValidationReport, summary_only: bool = False) -> str:
    """Render TreeValidationReport as human-readable text."""
    lines = []
    s = report.summary
    total_wf = len(report.results)
    lines.append(f"Root: {report.root}")
    lines.append(f"Workflows: {total_wf} | Steps: {s['ok']} OK, {s['fail']} FAIL, {s['skip']} SKIP, {s['error']} ERROR")
    lines.append("")

    if not summary_only:
        for r in report.results:
            name = r.relative_path
            if r.error:
                lines.append(f"  {name}: ERROR ({r.error})")
                continue
            n_ok = sum(1 for sr in r.step_results if sr.status == "ok")
            n_fail = sum(1 for sr in r.step_results if sr.status == "fail")
            n_skip = sum(1 for sr in r.step_results if sr.status == "skip")
            total = len(r.step_results)
            lines.append(f"  {name}: {total} steps ({n_ok} OK, {n_fail} FAIL, {n_skip} SKIP)")
            for sr in r.step_results:
                if sr.status == "fail":
                    for err in sr.errors:
                        lines.append(f"    Step {sr.step} ({sr.tool_id}): {err}")

    lines.append("---")
    lines.append(f"Summary: {s['ok']} OK, {s['fail']} FAIL, {s['skip']} SKIP, {s['error']} ERROR")
    return "\n".join(lines)


def format_tree_markdown(report: TreeValidationReport) -> str:
    """Render TreeValidationReport as Markdown."""
    s = report.summary
    total_wf = len(report.results)
    lines = [
        "# Workflow Validation Report",
        "",
        f"Root: `{report.root}`",
        f"Workflows: {total_wf} | Steps: {s['ok']} OK, {s['fail']} FAIL, {s['skip']} SKIP, {s['error']} ERROR",
        "",
    ]

    failure_details: List[str] = []
    for category, wf_results in sorted(report.by_category().items()):
        lines.append(f"## {category} ({len(wf_results)} workflows)")
        lines.append("")
        lines.append("| Workflow | Steps | OK | Fail | Skip | Details |")
        lines.append("| --- | --- | --- | --- | --- | --- |")

        for r in wf_results:
            name = os.path.basename(r.relative_path)
            if r.error:
                lines.append(f"| {name} | - | - | - | - | ERROR: {r.error} |")
                continue

            n_ok = sum(1 for sr in r.step_results if sr.status == "ok")
            n_fail = sum(1 for sr in r.step_results if sr.status == "fail")
            n_skip = sum(1 for sr in r.step_results if sr.status == "skip")
            total = len(r.step_results)
            fails = [sr for sr in r.step_results if sr.status == "fail"]
            detail = ""
            if fails:
                detail = f"{len(fails)} failure(s)"
                for sr in fails:
                    for err in sr.errors:
                        failure_details.append(f"- **{r.relative_path}** Step {sr.step} ({sr.tool_id}): {err}")
            lines.append(f"| {name} | {total} | {n_ok} | {n_fail} | {n_skip} | {detail} |")

        lines.append("")

    if failure_details:
        lines.append("## Failure Details")
        lines.append("")
        lines.extend(failure_details)
        lines.append("")

    return "\n".join(lines)


def format_json_single(results: List[StepResult], workflow_path: str) -> dict:
    return {
        "workflow": workflow_path,
        "results": [
            {
                "step": r.step,
                "tool_id": r.tool_id,
                "version": r.version,
                "status": r.status,
                "errors": r.errors,
            }
            for r in results
        ],
        "summary": {
            "ok": sum(1 for r in results if r.status == "ok"),
            "fail": sum(1 for r in results if r.status == "fail"),
            "skip": sum(1 for r in results if r.status == "skip"),
        },
    }


def format_json_tree(report: TreeValidationReport) -> dict:
    return {
        "root": report.root,
        "workflows": [
            {
                "path": r.relative_path,
                "category": r.category,
                "error": r.error,
                "results": (
                    [
                        {
                            "step": sr.step,
                            "tool_id": sr.tool_id,
                            "version": sr.version,
                            "status": sr.status,
                            "errors": sr.errors,
                        }
                        for sr in r.step_results
                    ]
                    if not r.error
                    else []
                ),
                "summary": (
                    {
                        "ok": sum(1 for sr in r.step_results if sr.status == "ok"),
                        "fail": sum(1 for sr in r.step_results if sr.status == "fail"),
                        "skip": sum(1 for sr in r.step_results if sr.status == "skip"),
                    }
                    if not r.error
                    else None
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


def _all_reports_to_files(options: ValidateOptions) -> bool:
    """True if all --report-* flags point to files (none writing to stdout)."""
    for dest in [options.report_json, options.report_markdown]:
        if dest is not None and dest == "-":
            return False
    return True


# -- Entry point --


def run_validate(options: ValidateOptions) -> int:
    """Run validation pipeline. Returns exit code."""
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
        report = validate_tree(options.workflow_path, tool_info)
        return _emit_tree_results(options, report)
    else:
        workflow = load_workflow(options.workflow_path)
        results = validate_workflow_cli(workflow, tool_info)
        return _emit_single_results(options, results)


def _emit_single_results(options: ValidateOptions, results: List[StepResult]) -> int:
    has_explicit_report = options.report_json is not None or options.report_markdown is not None

    if options.report_json is not None:
        data = format_json_single(results, options.workflow_path)
        _write_output(json.dumps(data, indent=2), options.report_json)

    if options.report_markdown is not None:
        tree_report = TreeValidationReport(root=options.workflow_path)
        tree_report.results.append(
            WorkflowValidationResult(
                path=options.workflow_path,
                relative_path=os.path.basename(options.workflow_path),
                category="",
                step_results=results,
            )
        )
        _write_output(format_tree_markdown(tree_report), options.report_markdown)

    if not has_explicit_report:
        print(format_text(results, summary_only=options.summary))
    elif _all_reports_to_files(options):
        print(format_text(results, summary_only=True), file=sys.stderr)

    has_failures = any(r.status == "fail" for r in results)
    has_skips = any(r.status == "skip" for r in results)

    if has_failures:
        return 1
    elif has_skips and options.strict:
        return 2
    return 0


def _emit_tree_results(options: ValidateOptions, report: TreeValidationReport) -> int:
    has_explicit_report = options.report_json is not None or options.report_markdown is not None

    if options.report_json is not None:
        data = format_json_tree(report)
        _write_output(json.dumps(data, indent=2), options.report_json)

    if options.report_markdown is not None:
        _write_output(format_tree_markdown(report), options.report_markdown)

    if not has_explicit_report:
        print(format_tree_text(report, summary_only=options.summary))
    elif _all_reports_to_files(options):
        print(format_tree_text(report, summary_only=True), file=sys.stderr)

    s = report.summary
    if s["fail"] > 0 or s["error"] > 0:
        return 1
    elif s["skip"] > 0 and options.strict:
        return 2
    return 0
