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
from dataclasses import dataclass
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
    Classification,
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
UNCHECKED = "unchecked"
NOT_XML = "not reviewed: only XML tools are analysed"
NO_TOOLS = "no tools found"


@dataclass(frozen=True)
class FailOn:
    """The --fail-on conditions: a severity index, and whether codes or unchecked locations fail."""

    severity: int | None = None
    uncheckable: bool = False
    unchecked: bool = False

    @classmethod
    def parse(cls, values: list[str]) -> FailOn:
        severity = min((SEVERITIES.index(v) for v in values if v in SEVERITIES), default=None)
        return cls(severity, UNCHECKABLE in values, UNCHECKED in values)

    def met(self, report: Report, classification: Classification) -> bool:
        if self.severity is not None and any(SEVERITIES.index(f.severity) >= self.severity for f in report.findings):
            return True
        return (self.uncheckable and bool(classification.codes)) or (
            self.unchecked and bool(classification.unchecked_locations)
        )


@dataclass(frozen=True)
class Reviewed:
    tool_source: ToolSource
    report: Report


@dataclass(frozen=True)
class NotReviewed:
    error: str
    # The tool, when it loaded but its review raised.
    tool_source: ToolSource | None = None

    def to_dict(self) -> dict[str, Any]:
        tool_id, tool_version = _identify(self.tool_source)
        return {
            "tool_id": tool_id,
            "tool_version": tool_version,
            "error": self.error,
            "codes": [Uncheckable.REVIEW_FAILED],
        }


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    threshold = SEVERITIES.index(args.min_severity)
    fail_on = FailOn.parse(args.fail_on)
    judge = AnthropicJudge() if args.judge else None
    reports: dict[str, dict[str, Any]] = {}
    failed = False
    for path, result in _reviews(args.tools):
        if isinstance(result, NotReviewed):
            failed = True
            reports[path] = result.to_dict()
            if not args.json:
                print(f"{path}\n  ERROR    {result.error}")
            continue
        report = result.report
        if judge is not None:
            judge_report(result.tool_source, report, judge)
        tool_version = result.tool_source.parse_version()
        classification = classify(report)
        reports[path] = {
            "tool_id": report.tool_id,
            "tool_version": tool_version,
            **report.to_dict(),
            "codes": classification.codes,
            "uncheckable_locations": classification.unchecked_locations,
        }
        if fail_on.met(report, classification):
            failed = True
        if not args.json:
            _print_report(path, tool_version, report, threshold, classification)
    if args.json:
        json.dump(reports, sys.stdout, indent=1)
    return 1 if failed else 0


def _parser() -> argparse.ArgumentParser:
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
        choices=(*SEVERITIES, UNCHECKABLE, UNCHECKED),
        default=[],
        help="exit 1 when any finding, vulnerability or capability, is at or above this severity (--judge verdicts"
        f" do not change this); with '{UNCHECKABLE}' when a tool has an uncheckable code; with '{UNCHECKED}' when a"
        " tool has an unchecked location (uncheckable_locations), templates the review did not analyse included;"
        " repeatable",
    )
    parser.add_argument(
        "--judge",
        action="store_true",
        help="ask Claude whether each vulnerability of medium severity or above is real (needs Anthropic credentials)",
    )
    return parser


def _reviews(paths: list[str]) -> Iterator[tuple[str, Reviewed | NotReviewed]]:
    for path, found in _tool_sources(paths):
        if isinstance(found, str):
            yield path, NotReviewed(found)
            continue
        try:
            report = review_tool_source(found)
        except Exception as e:
            yield path, NotReviewed(_describe_error(e), found)
        else:
            yield path, Reviewed(found, report)


def _tool_sources(paths: list[str]) -> Iterator[tuple[str, ToolSource | str]]:
    """Each XML tool of the paths once, under the first path that reaches it, or why a path is not reviewed."""
    seen: set[str] = set()
    for path in paths:
        found = _directory_tool_files(path) if os.path.isdir(path) else [(path, True)]
        if not found:
            yield path, NO_TOOLS
        for shown, xml in found:
            real = os.path.realpath(shown)
            if real in seen:
                continue
            seen.add(real)
            if not xml:
                yield shown, NOT_XML
                continue
            try:
                tool_source = get_tool_source(shown)
            except Exception as e:
                yield shown, _describe_error(e)
                continue
            yield shown, tool_source if isinstance(tool_source, XmlToolSource) else NOT_XML


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
    path: str, tool_version: str | None, report: Report, threshold: int, classification: Classification
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
    for location, why in classification.unchecked_locations.items():
        print(f"  NOTE     unchecked {location}: {why}")
    for code, why in classification.reasons.items():
        print(f"  NOTE     {code}: {why}")


def _where(finding: Finding) -> str:
    where = finding.location + (f":{finding.line}" if finding.line else "")
    if finding.more_lines:
        where += f" (+{len(finding.more_lines)})"
    return where


if __name__ == "__main__":
    sys.exit(main())
