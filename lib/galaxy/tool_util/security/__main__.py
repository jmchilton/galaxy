"""``python -m galaxy.tool_util.security tool.xml [...]``: print the security review of tools."""

from __future__ import annotations

import argparse
import json
import sys

from galaxy.tool_util.parser import get_tool_source
from . import review_tool_source
from .charsets import SEVERITIES
from .judge import (
    AnthropicJudge,
    judge_report,
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m galaxy.tool_util.security", description=__doc__)
    parser.add_argument("tools", nargs="+", help="tool XML files")
    parser.add_argument("--json", action="store_true", help="print one JSON document with all reports")
    parser.add_argument("--min-severity", choices=SEVERITIES, default="info")
    parser.add_argument(
        "--judge",
        action="store_true",
        help="ask Claude whether each vulnerability of medium severity or above is real (needs Anthropic credentials)",
    )
    args = parser.parse_args(argv)
    threshold = SEVERITIES.index(args.min_severity)
    reports = {}
    judge = AnthropicJudge() if args.judge else None
    for path in args.tools:
        tool_source = get_tool_source(path)
        report = review_tool_source(tool_source)
        if judge is not None:
            judge_report(tool_source, report, judge)
        reports[path] = report.to_dict()
        if args.json:
            continue
        print(f"{path} ({report.tool_id})")
        for finding in report.sorted():
            if SEVERITIES.index(finding.severity) < threshold:
                continue
            where = finding.location + (f":{finding.line}" if finding.line else "")
            if finding.more_lines:
                where += f" (+{len(finding.more_lines)})"
            print(f"  {finding.severity.upper():8} {finding.rule:22} {where:18} {finding.message}")
            if finding.assessment:
                verdict, reason = finding.assessment["verdict"], finding.assessment["reason"]
                attack = f" Value: {finding.assessment['attack']}" if finding.assessment.get("attack") else ""
                print(f"           model says {verdict}: {reason}{attack}")
        for note in report.unanalyzed:
            print(f"  NOTE     {note}")
    if args.json:
        json.dump(reports, sys.stdout, indent=1)
    return 0


if __name__ == "__main__":
    sys.exit(main())
