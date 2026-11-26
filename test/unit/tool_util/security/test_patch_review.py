import json
import os
from pathlib import Path

import pytest

from galaxy.tool_util.parser import get_tool_source
from galaxy.tool_util.patches import load_tool_patch_database
from galaxy.tool_util.security import __main__ as security_main
from galaxy.tool_util.security.__main__ import main
from galaxy.tool_util.security.classify import (
    NOT_CHECKABLE,
    Uncheckable,
)
from galaxy.tool_util.security.judge import Assessment
from galaxy.tool_util.security.patch_review import (
    PatchReview,
    review_patches,
)
from galaxy.tool_util.security.report import (
    NOT_ANALYSED,
    Report,
)
from galaxy.tool_util.unittest_utils import functional_test_tool_path
from galaxy.tool_util.unittest_utils.tool_patches import (
    replace_text_op,
    security_patch,
    write_collection,
)

TOOL = functional_test_tool_path("identifier_single.xml")
KEY_FILE = "_local/identifier_single/1.0.0.yml"
PATCH_KEYS = ("patches", "before", "cleared", "introduced", "notes_added")
ECHO = "echo 'identifier $input1.element_identifier' > 'output1';"
DOC = "Jobs whose input identifier held other characters than letters, digits, '_', '-' and '.' now print them as '_'."
CLEANING = security_patch(
    [
        replace_text_op(
            "command",
            ECHO,
            "#import re\n"
            '#set $clean_identifier = $re.sub(r"[^\\w.-]", "_", str($input1.element_identifier))\n'
            "echo 'identifier $clean_identifier' > 'output1';",
        )
    ],
    "unusual_inputs",
    DOC,
)
COSMETIC = security_patch(
    [
        replace_text_op(
            "command", ECHO, "#set $label = 'identifier'\necho '$label $input1.element_identifier' > 'output1';"
        )
    ],
    "unusual_inputs",
    DOC,
)
GUID = "toolshed.example.org/repos/owner/repo/identifier_single/1.0.0"
UNQUOTING = security_patch(
    [replace_text_op("command", "> 'output1';", "> 'output1'; echo $input1.name;")], "unusual_inputs", DOC
)
DECODING = security_patch(
    [
        replace_text_op(
            "command",
            ECHO,
            "echo 'identifier ${str($input1.element_identifier).encode().decode(\"unicode_escape\")}' > 'output1';",
        )
    ],
    "unusual_inputs",
    DOC,
)
AWK_TOOL = """<tool id="sanitized_awk" name="sanitized_awk" version="1.0">
    <command><![CDATA[awk 'BEGIN { print $x }' > '$out']]></command>
    <inputs>
        <param name="x" type="text" value="a">
            <sanitizer invalid_char=""><valid initial="string.letters"><add value="CHAR"/></valid></sanitizer>
        </param>
    </inputs>
    <outputs><data name="out" format="txt"/></outputs>
</tool>
"""


def _review(tmp_path: Path, patch: dict):
    db = load_tool_patch_database([str(write_collection(tmp_path / "c", {KEY_FILE: patch}))])
    return review_patches(get_tool_source(TOOL), db)


def _rules(findings) -> set[tuple[str, str]]:
    return {(f.rule, f.severity) for f in findings}


def test_cleaning_patch_clears_its_finding(tmp_path: Path) -> None:
    review = _review(tmp_path, CLEANING)
    assert review.patch is not None and [s.state for s in review.patch.states] == ["applied"]
    assert ("shell-injection", "high") in _rules(review.cleared)
    assert review.introduced == []


def test_findings_match_across_rewritten_template_text(tmp_path: Path) -> None:
    review = _review(tmp_path, COSMETIC)
    assert review.patch is not None and review.patch.states[0].state == "applied"
    assert ("shell-injection", "high") in _rules(review.after.findings)
    assert (review.cleared, review.introduced) == ([], [])


def test_patch_introducing_a_finding_is_reported(tmp_path: Path) -> None:
    review = _review(tmp_path, UNQUOTING)
    assert ("argument-injection", "medium") in _rules(review.introduced)
    assert {ref.param for f in review.introduced for ref in f.refs} == {"input1"}


def test_unquoting_the_reviewed_value_is_a_new_finding(tmp_path: Path) -> None:
    unquote = security_patch(
        [replace_text_op("command", ECHO, "echo identifier $input1.element_identifier > 'output1';")],
        "unusual_inputs",
        DOC,
    )
    review = _review(tmp_path, unquote)
    assert ("shell-injection", "high") in _rules(review.introduced)
    assert review.regressed


def _awk_review(tmp_path: Path, before: str, after: str):
    tool = tmp_path / "sanitized_awk.xml"
    tool.write_text(AWK_TOOL.replace("CHAR", before))
    op = {
        "replace_element": {
            "path": "inputs/param[@name='x']/sanitizer/valid/add",
            "old": f'<add value="{before}"/>',
            "new": f'<add value="{after}"/>',
            "occurrences": 1,
        }
    }
    patch = security_patch([op], "ordinary_inputs", DOC)
    collection = write_collection(tmp_path / "c", {"_local/sanitized_awk/1.0.yml": patch})
    return tool, collection, review_patches(get_tool_source(str(tool)), load_tool_patch_database([str(collection)]))


def test_raising_a_findings_severity_is_new(tmp_path: Path) -> None:
    tool, collection, review = _awk_review(tmp_path, "/", ";")
    assert _rules(review.before.findings) == {("nested-interpreter", "medium")}
    assert _rules(review.introduced) == {("nested-interpreter", "high")}
    assert review.cleared == [] and review.regressed
    assert main([str(tool), "--tool-patch-path", str(collection)]) == 1


def test_lowering_a_findings_severity_clears_nothing(tmp_path: Path) -> None:
    _, _, review = _awk_review(tmp_path, ";", "/")
    assert _rules(review.after.findings) == {("nested-interpreter", "medium")}
    assert (review.cleared, review.introduced) == ([], [])
    assert not review.regressed


IMPORTING_TOOL = """<tool id="importing" name="importing" version="1.0">
    <command><![CDATA[#import os, subprocess
echo ${os.getcwd()} > '$out']]></command>
    <inputs><param name="a" type="integer" value="1"/></inputs>
    <outputs><data name="out" format="txt"/></outputs>
</tool>
"""


@pytest.mark.parametrize("new", ["#import os, subprocess, re", "#import subprocess, os"], ids=["append", "reorder"])
def test_capability_findings_match_across_edited_import_lines(tmp_path: Path, new: str) -> None:
    tool = tmp_path / "importing.xml"
    tool.write_text(IMPORTING_TOOL)
    patch = security_patch([replace_text_op("command", "#import os, subprocess", new)], "ordinary_inputs", DOC)
    db = load_tool_patch_database([str(write_collection(tmp_path / "c", {"_local/importing/1.0.yml": patch}))])
    review = review_patches(get_tool_source(str(tool)), db)
    assert ("template-exec", "critical") in _rules(review.after.findings)
    assert (review.cleared, review.introduced) == ([], [])


def test_patch_making_a_finding_uncheckable_is_a_regression(tmp_path: Path) -> None:
    review = _review(tmp_path, DECODING)
    assert review.introduced == []
    assert review.notes_added == [
        f"unchecked command: {NOT_CHECKABLE}",
        f"{Uncheckable.REWRITES}: its templates change values with decode",
    ]
    assert review.regressed


def test_new_reason_for_an_unchecked_location_is_not_a_note_added() -> None:
    before = Report(unchecked_locations={"command": NOT_ANALYSED})
    after = Report(unchecked_locations={"command": NOT_CHECKABLE})
    review = PatchReview(before=before, after=after, patched=get_tool_source(TOOL), patch=None)
    assert review.notes_added == [] and not review.regressed


def test_unmatched_tool_has_no_patch_changes(tmp_path: Path) -> None:
    db = load_tool_patch_database([str(write_collection(tmp_path / "c", {"_local/other/1.0.yml": CLEANING}))])
    review = review_patches(get_tool_source(TOOL), db)
    assert review.patch is None
    assert ("shell-injection", "high") in _rules(review.after.findings)
    assert (review.cleared, review.introduced, review.notes_added) == ([], [], [])


def _cli_json(argv: list[str], capsys: pytest.CaptureFixture[str]) -> tuple[int, dict]:
    exit_code = main([*argv, "--json"])
    (report,) = json.loads(capsys.readouterr().out).values()
    return exit_code, report


def _usage_error(argv: list[str], capsys: pytest.CaptureFixture[str]) -> str:
    with pytest.raises(SystemExit) as exit_info:
        main(argv)
    assert exit_info.value.code == 2
    return capsys.readouterr().err


def test_cli_rejects_a_missing_collection(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    error = _usage_error([TOOL, "--tool-patch-path", str(tmp_path / "missing")], capsys)
    assert "is not a loadable tool patch collection" in error


@pytest.mark.parametrize(
    "argv,error",
    [
        ([os.path.dirname(TOOL), "--guid", GUID], "--guid needs exactly one tool file"),
        ([TOOL, "--guid", "identifier_single"], "--guid is not a Tool Shed guid"),
        ([TOOL, "--guid", "toolshed.example.org/repos/owner/repo"], "--guid is not a Tool Shed guid"),
    ],
    ids=["directory", "not-shed", "short"],
)
def test_cli_rejects_a_guid_it_cannot_use(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], argv: list[str], error: str
) -> None:
    collection = write_collection(tmp_path / "c", {KEY_FILE: CLEANING})
    assert error in _usage_error([*argv, "--tool-patch-path", str(collection)], capsys)


@pytest.mark.parametrize(
    "argv,error",
    [
        (["--guid", GUID], "--guid"),
        (["--fail-on", "mismatch"], "--fail-on mismatch"),
        (["--fail-on", "uncleared"], "--fail-on uncleared"),
    ],
    ids=["guid", "fail-on-mismatch", "fail-on-uncleared"],
)
def test_cli_rejects_patch_options_without_a_collection(
    capsys: pytest.CaptureFixture[str], argv: list[str], error: str
) -> None:
    assert f"{error} needs --tool-patch-path" in _usage_error([TOOL, *argv], capsys)


def test_cli_matches_shed_keys_by_guid(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    collection = write_collection(tmp_path / "c", {"owner/repo/identifier_single/1.0.0.yml": CLEANING})
    _, unmatched = _cli_json([TOOL, "--tool-patch-path", str(collection)], capsys)
    assert unmatched["patches"] is None
    exit_code, report = _cli_json([TOOL, "--tool-patch-path", str(collection), "--guid", GUID], capsys)
    assert exit_code == 0
    assert [s["state"] for s in report["patches"]] == ["applied"]


@pytest.mark.parametrize("patch,exit_code", [(CLEANING, 0), (UNQUOTING, 1)], ids=["clears", "introduces"])
def test_cli_reports_patch_review(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], patch: dict, exit_code: int
) -> None:
    _, unpatched = _cli_json([TOOL], capsys)
    assert not set(unpatched) & set(PATCH_KEYS)
    collection = write_collection(tmp_path / "c", {KEY_FILE: patch})
    got, report = _cli_json([TOOL, "--tool-patch-path", str(collection)], capsys)
    assert got == exit_code
    assert set(report) == set(unpatched) | set(PATCH_KEYS)
    assert [s["key"] for s in report["patches"]] == ["_local/identifier_single/1.0.0"]
    assert bool(report["introduced"]) is bool(exit_code)
    assert set(report["before"]) == set(unpatched) - {"tool_version"}
    assert report["tool_version"] == "1.0.0"


def test_cli_text_shows_patch_states_and_cleared_findings(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    collection = write_collection(tmp_path / "c", {KEY_FILE: CLEANING})
    assert main([TOOL, "--tool-patch-path", str(collection)]) == 0
    lines = capsys.readouterr().out.splitlines()
    assert lines[1].split() == ["PATCH", "applied", "security", "_local/identifier_single/1.0.0"]
    assert any(line.startswith("  CLEARED  HIGH     shell-injection") for line in lines)
    assert not any(line.startswith("  NEW ") for line in lines)


def test_cli_min_severity_hides_cleared_but_not_new_findings(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    for name, patch in (("clears", CLEANING), ("introduces", UNQUOTING)):
        collection = write_collection(tmp_path / name, {KEY_FILE: patch})
        main([TOOL, "--tool-patch-path", str(collection), "--min-severity", "critical"])
    lines = capsys.readouterr().out.splitlines()
    assert not any(line.startswith("  CLEARED ") for line in lines)
    assert any(line.startswith("  NEW      MEDIUM   argument-injection") for line in lines)


def _compat_patch(ops: list[dict]) -> dict:
    return {
        "format_version": 1,
        "kind": "compat",
        "needed_from": "26.1",
        "galaxy_change": [{"repo": "galaxyproject/galaxy", "pr": 2}],
        "upstream": [],
        "reproducibility": "identical",
        "reproducibility_reason": "restores what older Galaxy releases did",
        "reproducibility_doc": "No job behaves differently.",
        "ops": ops,
    }


STALE_OP = replace_text_op("command", "echo 'no such text'", "echo 'other'")


@pytest.mark.parametrize(
    "patch,fail_on,exit_code",
    [
        (security_patch([STALE_OP], "unusual_inputs", DOC), [], 0),
        (security_patch([STALE_OP], "unusual_inputs", DOC), ["--fail-on", "mismatch"], 1),
        (_compat_patch([STALE_OP]), ["--fail-on", "mismatch"], 0),
    ],
    ids=["default", "fail-on", "compat"],
)
def test_cli_fails_on_a_mismatched_security_patch_only_when_asked(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], patch: dict, fail_on: list[str], exit_code: int
) -> None:
    collection = write_collection(tmp_path / "c", {KEY_FILE: patch})
    got, report = _cli_json([TOOL, "--tool-patch-path", str(collection), *fail_on], capsys)
    assert [s["state"] for s in report["patches"]] == ["mismatch"]
    assert got == exit_code


def test_cli_fails_on_a_patch_breaking_the_template(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    broken = security_patch([replace_text_op("command", ECHO, "#if $input1\n" + ECHO)], "unusual_inputs", DOC)
    collection = write_collection(tmp_path / "c", {KEY_FILE: broken})
    assert main([TOOL, "--tool-patch-path", str(collection)]) == 1
    lines = capsys.readouterr().out.splitlines()
    assert [line for line in lines if line.startswith("  NEW ")] == [
        "  NEW      NOTE     command: template does not compile (ParseError)",
        f"  NEW      NOTE     unchecked command: {NOT_ANALYSED}",
    ]


def test_cli_lists_a_patch_review_that_raises_as_an_error(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    def raises(*args, **kwargs):
        raise ValueError("boom")

    monkeypatch.setattr(security_main, "review_patches", raises)
    collection = write_collection(tmp_path / "c", {KEY_FILE: CLEANING})
    exit_code, report = _cli_json([TOOL, "--tool-patch-path", str(collection)], capsys)
    assert exit_code == 1
    assert report["error"] == "ValueError: boom"
    assert report["tool_id"] == "identifier_single"


class _RecordingJudge:
    def __init__(self) -> None:
        self.contexts: list[str] = []

    def assess(self, system: str, tool_context: str, question: str) -> Assessment:
        self.contexts.append(tool_context)
        return Assessment(verdict="arg", attack=None, reason="Stand-in.")


def test_cli_judges_the_patched_source(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    judge = _RecordingJudge()
    monkeypatch.setattr(security_main, "AnthropicJudge", lambda: judge)
    collection = write_collection(tmp_path / "c", {KEY_FILE: UNQUOTING})
    exit_code, report = _cli_json([TOOL, "--judge", "--tool-patch-path", str(collection)], capsys)
    assert exit_code == 1
    assert judge.contexts and all("echo $input1.name" in context for context in judge.contexts)
    medium = [f for f in report["introduced"] if f["severity"] == "medium"]
    assert medium and all(f["assessment"]["verdict"] == "arg" for f in medium)


UNCLEARED = ["--fail-on", "uncleared"]


@pytest.mark.parametrize(
    "patch,fail_on,exit_code",
    [
        (COSMETIC, [], 0),
        (CLEANING, UNCLEARED, 0),
        (COSMETIC, UNCLEARED, 1),
        (_compat_patch(COSMETIC["ops"]), UNCLEARED, 0),
    ],
    ids=["default", "clears", "clears-nothing", "compat"],
)
def test_cli_fails_on_an_applied_security_patch_that_clears_nothing_only_when_asked(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], patch: dict, fail_on: list[str], exit_code: int
) -> None:
    collection = write_collection(tmp_path / "c", {KEY_FILE: patch})
    got, report = _cli_json([TOOL, "--tool-patch-path", str(collection), *fail_on], capsys)
    assert [s["state"] for s in report["patches"]] == ["applied"]
    assert got == exit_code
