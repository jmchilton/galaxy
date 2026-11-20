"""Structured sources and breakout characters of findings, which let Galaxy check the values of a job."""

from __future__ import annotations

import json
import time

import pytest

from galaxy.tool_util.security import (
    Report,
    ReviewTimeout,
    SourceRef,
)
from galaxy.tool_util.security.charsets import (
    HIGH,
    SHELL_EXEC,
)
from galaxy.tool_util.security.report import (
    DATASET_ATTRIBUTE,
    ELEMENT_IDENTIFIER,
    GROUP_TAGS,
    METADATA,
    OPAQUE,
    RAW,
    SPECIAL,
    TEXT,
)
from .test_review import review

UNSANITIZED = '<options sanitize="False"/>'


def refs(report: Report) -> set[SourceRef]:
    return {ref for f in report.findings for ref in f.refs}


@pytest.mark.parametrize(
    "command,extra,expected",
    [
        ("echo '$text'", "", SourceRef(TEXT, "text")),
        ("echo '${text.value}'", "", SourceRef(RAW, "text")),
        ("echo '$text.strip()'", "", SourceRef(RAW, "text")),
        ("echo '$input.element_identifier'", "", SourceRef(ELEMENT_IDENTIFIER, "input")),
        ("echo '$input.name_and_ext'", "", SourceRef(ELEMENT_IDENTIFIER, "input")),
        ("#for $e in $flat\necho '$e.element_identifier'\n#end for", "", SourceRef(ELEMENT_IDENTIFIER, "flat")),
        ("#for $e in $nested\necho '$e.name'\n#end for", "", SourceRef(ELEMENT_IDENTIFIER, "nested")),
        ("echo '$flat.name'", "", SourceRef(ELEMENT_IDENTIFIER, "flat")),
        ("echo '$input.name'", UNSANITIZED, SourceRef(DATASET_ATTRIBUTE, "input", "name")),
        ("echo '$input.info'", UNSANITIZED, SourceRef(DATASET_ATTRIBUTE, "input", "info")),
        ("echo '$input.dataset.info'", UNSANITIZED, SourceRef(DATASET_ATTRIBUTE, "input", "info")),
        ("echo '$input.metadata.sample_names'", UNSANITIZED, SourceRef(METADATA, "input", "sample_names")),
        ("#for $g in $input.groups\necho '$g'\n#end for", "", SourceRef(GROUP_TAGS, "input")),
        ("echo $column", UNSANITIZED, SourceRef(TEXT, "column")),
        ("echo '${column.value}'", "", SourceRef(RAW, "column")),
        ("echo '$__user_email__'", UNSANITIZED, SourceRef(SPECIAL, None, "__user_email__")),
        ("echo '$input.unsanitized.name'", "", SourceRef(OPAQUE, "input")),
        ("echo '$__user__.username'", "", SourceRef(OPAQUE)),
        ("echo '${opts.adv.deep.element_identifier}'", "", SourceRef(ELEMENT_IDENTIFIER, "opts.adv.deep")),
        ("#for $r in $rows\necho '${r.label.value}'\n#end for", "", SourceRef(RAW, "rows.label")),
    ],
)
def test_finding_names_its_source(tmp_path, command, extra, expected):
    assert expected in refs(review(tmp_path, command, extra=extra))


def test_param_path():
    assert SourceRef(RAW, "opts.adv.deep").param_path == ("opts", "adv", "deep")
    assert SourceRef(SPECIAL, None, "__user_email__").param_path == ()


def test_sources_keep_their_text(tmp_path):
    (finding,) = review(tmp_path, "echo '$input.element_identifier'").findings
    assert finding.source == "element identifier of dataset 'input' (not sanitized)"


def high(report: Report):
    (finding,) = [f for f in report.findings if f.severity == HIGH]
    return finding


@pytest.mark.parametrize(
    "command,breakout,requires",
    [
        # A quote leaves single quotes, and a command character after it starts a command.
        ("echo '${free}'", frozenset("'"), SHELL_EXEC),
        ("echo ${free}", SHELL_EXEC, frozenset()),
        # A substitution, or a closing quote that a command character follows.
        ('echo "${free}"', frozenset('`$"'), SHELL_EXEC),
        # In $'...' a backslash escapes the closing quote.
        ("echo $'${free}'", frozenset("'\\"), SHELL_EXEC),
        # Escaping writes the quote that closes the string; the value has to bring the command characters.
        ("#import shlex\necho '${shlex.quote(str($free))}'", SHELL_EXEC, frozenset()),
        ('echo "$json.dumps(str($free))"', frozenset("`$") | SHELL_EXEC, frozenset()),
        ('echo "${repr(str($free))}"', frozenset("`$") | SHELL_EXEC, frozenset()),
    ],
)
def test_breakout(tmp_path, command, breakout, requires):
    finding = high(review(tmp_path, command))
    assert (finding.breakout, finding.requires) == (breakout, requires)
    assert finding.checkable


@pytest.mark.parametrize(
    "command",
    [
        # Template code can write the character that leaves the quotes, whatever the user wrote.
        "echo \"${text.replace('Q', '`')}\"",
        "echo ${str($text).replace('__gt__', '>')}",
        "#import re\necho ${re.sub('_', ';', str($free))}",
        "#import urllib.parse\necho '${urllib.parse.unquote(str($free))}'",
        "#import base64\necho '${base64.b64decode(str($free))}'",
        "echo '${some_function($free)}'",
        "echo '${str($free).translate($table)}'",
    ],
)
def test_rewritten_values_are_not_checkable(tmp_path, command):
    report = review(tmp_path, command)
    findings = [f for f in report.findings if f.severity == HIGH and f.kind == "vulnerability"]
    assert findings
    assert all(not f.checkable and f.unchecked for f in findings)


def test_rewriting_that_cannot_add_a_breakout_character_stays_checkable(tmp_path):
    finding = high(review(tmp_path, "echo '${str($free).replace('_', '-').lower()}'"))
    assert finding.checkable and not finding.unchecked


@pytest.mark.parametrize(
    "command",
    [
        "echo '${''.join([\"'\", str($free)])}'",
        "#set $l = [\"'\", str($free)]\necho '${''.join($l)}'",
        "#set $l = [\"'\", str($free)]\necho '${''.join(reversed($l))}'",
    ],
)
def test_literal_elements_joined_with_a_value_are_not_the_users(tmp_path, command):
    finding = high(review(tmp_path, command))
    assert finding.unchecked and not finding.checkable


def test_writes_record_what_does_harm_outside_quotes(tmp_path):
    # `echo '$x' && echo '$y'`: a quote in x leaves the `;` of y unquoted. `no_quote` has no finding
    # (it cannot leave its quotes), but its `;` does harm once another value's quote frees it.
    report = review(tmp_path, "echo '${free}' && echo '${no_quote}' && echo '$word'")
    writes = report.writes["command"]
    assert writes[SourceRef(TEXT, "free")] == SHELL_EXEC
    assert writes[SourceRef(TEXT, "no_quote")] == SHELL_EXEC
    assert writes[SourceRef(TEXT, "word")] == frozenset()
    assert Report.from_dict(json.loads(json.dumps(report.to_dict()))).writes == report.writes


def test_a_quote_left_raw_by_escaping_closes(tmp_path):
    # repr() writes `"x'"`: its `"` closes the template's double quotes, and the value's own `'`
    # then opens single quotes that flip the rest of the line.
    report = review(tmp_path, """echo "${repr(str($quotes))}" && echo '$word'""")
    (finding,) = [f for f in report.findings if f.kind == "vulnerability" and f.refs == (SourceRef(TEXT, "quotes"),)]
    assert finding.closes == frozenset("'\"") and finding.checkable


def test_writes_are_left_out_when_a_value_is_rewritten(tmp_path):
    report = review(tmp_path, """echo '${str($no_quote).replace("Q", ";")}' && echo '${free}'""")
    assert "command" not in report.writes
    assert not any(f.checkable for f in report.findings if f.kind == "vulnerability")


def test_a_rewritten_value_makes_the_whole_template_uncheckable(tmp_path):
    # The rewrite can bring the quote that lets the other value out.
    report = review(tmp_path, """echo '${str($free).replace("Q", "'")}${text.value}'""")
    findings = [f for f in report.findings if f.kind == "vulnerability" and f.severity == HIGH]
    assert findings and not any(f.checkable for f in findings)


@pytest.mark.parametrize(
    "command",
    [
        "echo '${free}'\necho ${str($free).replace('Q', ';')}",
        "echo ${str($free).replace('Q', ';')}\necho '${free}'",
    ],
)
def test_a_rewritten_source_is_not_checkable_anywhere(tmp_path, command):
    # Whether the rewrite comes before or after a place that writes the value as it is.
    findings = [f for f in review(tmp_path, command).findings if f.kind == "vulnerability" and f.severity == HIGH]
    assert len(findings) == 2
    assert all(f.unchecked for f in findings)


def test_nested_shell(tmp_path):
    report = review(tmp_path, "sh -c 'echo ${free}'")
    breakout = {f.rule: (f.breakout, f.requires) for f in report.findings}
    # Closing the quotes of `sh -c '...'`, or a command character inside the nested shell.
    assert breakout == {
        "shell-injection": (frozenset("'"), SHELL_EXEC),
        "nested-interpreter": (SHELL_EXEC, frozenset()),
    }


def test_no_character_decides_the_program(tmp_path):
    report = review(tmp_path, "$free --version")
    (finding,) = [f for f in report.findings if f.rule == "command-position"]
    assert finding.breakout == frozenset()


def test_report_survives_json(tmp_path):
    report = review(tmp_path, "echo '$input.element_identifier' $text")
    restored = Report.from_dict(json.loads(json.dumps(report.to_dict())))
    assert restored.sorted() == report.sorted()
    assert restored.to_dict() == report.to_dict()


def test_timeout(tmp_path, monkeypatch):
    clock = iter([0.0, 100.0])
    monkeypatch.setattr(time, "monotonic", lambda: next(clock, 100.0))
    with pytest.raises(ReviewTimeout):
        review(tmp_path, "echo $text", timeout=1)
