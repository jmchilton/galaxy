"""The ``galaxy-tool-security-review`` command line."""

import json

from galaxy.tool_util.parser import get_tool_source
from galaxy.tool_util.security import review_tool_source
from galaxy.tool_util.security.__main__ import main
from galaxy.tool_util.security.spec import tool_path

STRAY_QUOTE = tool_path("stray_quote.xml")
SANITIZED = tool_path("sanitized_text_single_quoted.xml")


def test_text_lists_findings_by_tool(capsys):
    assert main([STRAY_QUOTE]) == 0
    lines = capsys.readouterr().out.splitlines()
    assert lines[0].startswith(f"{STRAY_QUOTE} (spec_stray_quote")
    assert sum("HIGH     shell-injection" in line for line in lines) == 2
    assert sum("LOW      option-injection" in line for line in lines) == 2


def test_min_severity_hides_lower_findings(capsys):
    assert main(["--min-severity", "high", STRAY_QUOTE]) == 0
    out = capsys.readouterr().out
    assert "shell-injection" in out
    assert "option-injection" not in out


def test_json_has_the_report_of_each_path(capsys):
    assert main(["--json", STRAY_QUOTE, SANITIZED]) == 0
    reports = json.loads(capsys.readouterr().out)
    assert list(reports) == [STRAY_QUOTE, SANITIZED]
    report = review_tool_source(get_tool_source(STRAY_QUOTE)).to_dict()
    assert {key: value for key, value in reports[STRAY_QUOTE].items() if key in report} == json.loads(
        json.dumps(report)
    )
