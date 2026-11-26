"""Print the static security review of Galaxy tools: tool files, or directories searched for them.

Only XML tools are reviewed. A tool that fails to load or review, a tool that is not XML, and a directory with no
tools are each listed with an error. A tool reached through several paths is reviewed once, under the first.
The exit code is 1 when a path has an error, or when --fail-on is met; 0 otherwise.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections.abc import Iterator
from typing import Any

from galaxy.tool_util.loader_directory import (
    find_possible_tools_from_path,
    looks_like_a_tool_xml,
)
from galaxy.tool_util.parser import get_tool_source
from galaxy.tool_util.parser.interface import ToolSource
from galaxy.tool_util.parser.xml import XmlToolSource
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
NOT_XML = "not reviewed: only XML tools are analysed"
NO_TOOLS = "no tools found"


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
            tool_id, tool_version = _identify(tool_source)
            reports[path] = {
                "tool_id": tool_id,
                "tool_version": tool_version,
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
    """Each XML tool of the paths once, under the first path that reaches it, or why a path is not reviewed."""
    seen: set[str] = set()
    for path in paths:
        found = _directory_tool_files(path) if os.path.isdir(path) else [(path, True)]
        if not found:
            yield path, None, NO_TOOLS
        for shown, xml in found:
            real = os.path.realpath(shown)
            if real in seen:
                continue
            seen.add(real)
            if not xml:
                yield shown, None, NOT_XML
                continue
            try:
                tool_source = get_tool_source(shown)
            except Exception as e:
                yield shown, None, _describe_error(e)
                continue
            if isinstance(tool_source, XmlToolSource):
                yield shown, tool_source, None
            else:
                yield shown, None, NOT_XML


def _directory_tool_files(directory: str) -> list[tuple[str, bool]]:
    """The tool files under the directory, shown under it, and whether each is XML; others are not loaded."""
    root = os.path.abspath(directory)
    found = find_possible_tools_from_path(directory, recursive=True, enable_beta_formats=True)
    return sorted((os.path.join(directory, os.path.relpath(path, root)), looks_like_a_tool_xml(path)) for path in found)


def _identify(tool_source: ToolSource | None) -> tuple[str | None, str | None]:
    if tool_source is None:
        return None, None
    try:
        return tool_source.parse_id(), tool_source.parse_version()
    except Exception:
        return None, None


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
