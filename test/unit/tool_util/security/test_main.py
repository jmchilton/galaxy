"""The ``galaxy-tool-security-review`` command line."""

import json
import os
import shutil

import pytest

from galaxy.tool_util.parser import get_tool_source
from galaxy.tool_util.security import (
    __main__ as cli,
    review_tool_source,
)
from galaxy.tool_util.security.__main__ import (
    main,
    NOT_XML,
)
from galaxy.tool_util.security.spec import tool_path
from galaxy.util import galaxy_directory

STRAY_QUOTE = tool_path("stray_quote.xml")
SANITIZED = tool_path("sanitized_text_single_quoted.xml")
FUNCTIONAL_TOOLS = os.path.join(galaxy_directory(), "test", "functional", "tools")


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


def test_text_names_the_tool_version(capsys):
    main([STRAY_QUOTE])
    assert capsys.readouterr().out.splitlines()[0] == f"{STRAY_QUOTE} (spec_stray_quote 1.0)"


def test_json_adds_version_and_codes(capsys):
    main(["--json", STRAY_QUOTE, tool_path("pipe_to_shell.xml")])
    reports = json.loads(capsys.readouterr().out)
    assert reports[STRAY_QUOTE]["tool_version"] == "1.0"
    assert reports[STRAY_QUOTE]["codes"] == []
    assert reports[tool_path("pipe_to_shell.xml")]["codes"] == ["uncheckable-letters-are-code"]


def _directory(tmp_path):
    shutil.copy(STRAY_QUOTE, tmp_path / "good.xml")
    nested = tmp_path / "nested"
    nested.mkdir()
    (nested / "broken.xml").write_text('<tool id="broken" name="broken" version="1"><command>')
    (nested / "macros.xml").write_text("<macros/>")
    return tmp_path


def test_directory_reviews_each_tool_and_reports_load_errors(tmp_path, capsys):
    directory = _directory(tmp_path)
    assert main(["--json", str(directory)]) == 1
    reports = json.loads(capsys.readouterr().out)
    good, broken = os.path.join(str(directory), "good.xml"), os.path.join(str(directory), "nested", "broken.xml")
    assert sorted(reports) == sorted([good, broken])
    assert reports[good]["tool_id"] == "spec_stray_quote"
    assert reports[broken]["error"]
    assert reports[broken]["codes"] == ["uncheckable-review-failed"]


def test_load_error_does_not_stop_the_run(tmp_path, capsys):
    broken = tmp_path / "broken.xml"
    broken.write_text("<tool")
    assert main([str(broken), STRAY_QUOTE]) == 1
    out = capsys.readouterr().out
    assert f"{broken}\n  ERROR" in out
    assert f"{STRAY_QUOTE} (spec_stray_quote 1.0)" in out


@pytest.mark.parametrize(
    "fail_on, exit_code",
    [(None, 0), ("critical", 0), ("high", 1), ("low", 1), ("uncheckable", 0)],
)
def test_fail_on_severity(fail_on, exit_code, capsys):
    assert main([STRAY_QUOTE, *(["--fail-on", fail_on] if fail_on else [])]) == exit_code


def test_fail_on_sees_findings_min_severity_hides(capsys):
    assert main(["--min-severity", "critical", "--fail-on", "high", STRAY_QUOTE]) == 1


def test_fail_on_uncheckable(capsys):
    pipe = tool_path("pipe_to_shell.xml")
    assert main(["--fail-on", "uncheckable", pipe]) == 1
    assert "  UNCHECKABLE uncheckable-letters-are-code: letters alone" in capsys.readouterr().out
    assert main(["--fail-on", "critical", "--fail-on", "uncheckable", pipe]) == 1
    assert main(["--fail-on", "critical", pipe]) == 0


def test_directory_lists_yaml_tools_as_not_reviewed(tmp_path, capsys):
    shutil.copy(STRAY_QUOTE, tmp_path / "good.xml")
    shutil.copy(os.path.join(FUNCTIONAL_TOOLS, "simple_constructs.yml"), tmp_path / "tool.yml")
    assert main(["--json", str(tmp_path)]) == 1
    reports = json.loads(capsys.readouterr().out)
    yml = os.path.join(str(tmp_path), "tool.yml")
    assert sorted(reports) == sorted([os.path.join(str(tmp_path), "good.xml"), yml])
    assert reports[yml] == {
        "tool_id": None,
        "tool_version": None,
        "error": NOT_XML,
        "codes": ["uncheckable-review-failed"],
    }


def test_yaml_tool_file_is_not_reviewed(capsys):
    yml = os.path.join(FUNCTIONAL_TOOLS, "simple_constructs.yml")
    assert main([yml]) == 1
    assert capsys.readouterr().out == f"{yml}\n  ERROR    {NOT_XML}\n"


def test_review_error_keeps_tool_id_and_version(monkeypatch, capsys):
    def fail(tool_source):
        raise ValueError("boom")

    monkeypatch.setattr(cli, "review_tool_source", fail)
    assert main(["--json", STRAY_QUOTE]) == 1
    report = json.loads(capsys.readouterr().out)[STRAY_QUOTE]
    assert report == {
        "tool_id": "spec_stray_quote",
        "tool_version": "1.0",
        "error": "ValueError: boom",
        "codes": ["uncheckable-review-failed"],
    }


def test_tool_reached_twice_is_reviewed_once_under_its_first_path(tmp_path, capsys):
    shutil.copy(STRAY_QUOTE, tmp_path / "good.xml")
    first = str(tmp_path / "good.xml")
    assert main([first, str(tmp_path), first]) == 0
    headers = [line for line in capsys.readouterr().out.splitlines() if not line.startswith(" ")]
    assert headers == [f"{first} (spec_stray_quote 1.0)"]


def test_directory_without_tools_is_an_error(tmp_path, capsys):
    (tmp_path / "macros.xml").write_text("<macros/>")
    assert main([str(tmp_path)]) == 1
    assert capsys.readouterr().out == f"{tmp_path}\n  ERROR    no tools found\n"
