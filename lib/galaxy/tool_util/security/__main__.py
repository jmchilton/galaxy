"""Print the static security review of Galaxy tools: tool files, or directories searched for them.

The exit code is 1 when a tool fails to load or review, or when --fail-on is met; 0 otherwise.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections.abc import Iterator
from typing import Any

from galaxy.tool_util.loader_directory import (
    is_tool_load_error,
    load_tool_sources_from_path,
)
from galaxy.tool_util.parser import get_tool_source
from galaxy.tool_util.parser.interface import ToolSource
from . import review_tool_source
from .charsets import SEVERITIES
from .classify import (
    classify,
    Uncheckable,
)
from .judge import (
    AnthropicJudge,
    judge_report,
)
from .report import (
    Finding,
    Report,
)

UNCHECKABLE = "uncheckable"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="galaxy-tool-security-review", description=__doc__)
    parser.add_argument("tools", nargs="+", help="tool files, or directories to search for tools recursively")
    parser.add_argument("--json", action="store_true", help="print one JSON document with all reports")
    parser.add_argument(
        "--min-severity",
        choices=SEVERITIES,
        default="info",
        help="hide findings below this severity in the text output (--json and --fail-on see every finding)",
    )
    parser.add_argument(
        "--fail-on",
        action="append",
        choices=(*SEVERITIES, UNCHECKABLE),
        default=[],
        help=f"exit 1 when a finding is at or above this severity, or with '{UNCHECKABLE}' when the review"
        " cannot decide a tool from its templates (repeatable)",
    )
    parser.add_argument(
        "--judge",
        action="store_true",
        help="ask Claude whether each vulnerability of medium severity or above is real (needs Anthropic credentials)",
    )
    args = parser.parse_args(argv)
    threshold = SEVERITIES.index(args.min_severity)
    fail_severities = [SEVERITIES.index(s) for s in args.fail_on if s != UNCHECKABLE]
    fail_threshold = min(fail_severities) if fail_severities else None
    reports: dict[str, dict[str, Any]] = {}
    judge = AnthropicJudge() if args.judge else None
    failed = False
    for path, tool_source, error in _tool_sources(args.tools):
        report = None
        if tool_source is not None:
            try:
                report = review_tool_source(tool_source)
            except Exception as e:
                error = _describe_error(e)
        if tool_source is None or report is None:
            failed = True
            reports[path] = {
                "tool_id": None,
                "tool_version": None,
                "error": error,
                "codes": [Uncheckable.REVIEW_FAILED],
            }
            if not args.json:
                print(f"{path}\n  ERROR    {error}")
            continue
        if judge is not None:
            judge_report(tool_source, report, judge)
        tool_version = tool_source.parse_version()
        classification = classify(report)
        reports[path] = {"tool_id": report.tool_id, "tool_version": tool_version, **report.to_dict()}
        reports[path]["codes"] = classification.codes
        if fail_threshold is not None and any(SEVERITIES.index(f.severity) >= fail_threshold for f in report.findings):
            failed = True
        if UNCHECKABLE in args.fail_on and classification.codes:
            failed = True
        if not args.json:
            _print_report(path, tool_version, report, threshold, classification.reasons)
    if args.json:
        json.dump(reports, sys.stdout, indent=1)
    return 1 if failed else 0


def _tool_sources(paths: list[str]) -> Iterator[tuple[str, ToolSource | None, str | None]]:
    """Each tool of the paths, or the error of one that fails to load."""
    for path in paths:
        if os.path.isdir(path):
            yield from _directory_tool_sources(path)
            continue
        try:
            yield path, get_tool_source(path), None
        except Exception as e:
            yield path, None, _describe_error(e)


def _directory_tool_sources(directory: str) -> Iterator[tuple[str, ToolSource | None, str | None]]:
    errors: dict[str, str] = {}

    def record(path: str, exc_info: Any) -> None:
        errors[path] = _describe_error(exc_info[1])

    found = load_tool_sources_from_path(
        directory, load_exception_handler=record, recursive=True, register_load_errors=True
    )
    root = os.path.abspath(directory)
    for path, tool_source in sorted(found, key=lambda item: item[0]):
        shown = os.path.join(directory, os.path.relpath(path, root))
        if is_tool_load_error(tool_source):
            yield shown, None, errors.get(path, "failed to load")
        else:
            yield shown, tool_source, None


def _describe_error(e: BaseException) -> str:
    return f"{type(e).__name__}: {e}"


def _print_report(
    path: str, tool_version: str | None, report: Report, threshold: int, reasons: dict[Uncheckable, str]
) -> None:
    print(f"{path} ({' '.join(part for part in (report.tool_id, tool_version) if part)})")
    for finding in report.sorted():
        if SEVERITIES.index(finding.severity) < threshold:
            continue
        print(f"  {finding.severity.upper():8} {finding.rule:22} {_where(finding):18} {finding.message}")
        if finding.assessment:
            verdict, reason = finding.assessment["verdict"], finding.assessment["reason"]
            attack = f" Value: {finding.assessment['attack']}" if finding.assessment.get("attack") else ""
            print(f"           model says {verdict}: {reason}{attack}")
    for note in report.unanalyzed:
        print(f"  NOTE     {note}")
    for code, why in reasons.items():
        print(f"  UNCHECKABLE {code}: {why}")


def _where(finding: Finding) -> str:
    where = finding.location + (f":{finding.line}" if finding.line else "")
    if finding.more_lines:
        where += f" (+{len(finding.more_lines)})"
    return where


if __name__ == "__main__":
    sys.exit(main())
