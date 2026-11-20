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
    "command,breakout",
    [
        # Only a quote leaves single quotes; what follows it is the command.
        ("echo '${free}'", frozenset("'")),
        ("echo ${free}", SHELL_EXEC),
        ('echo "${free}"', frozenset('`$"')),
        # In $'...' a backslash escapes the closing quote.
        ("echo $'${free}'", frozenset("'\\")),
        # shlex.quote writes the quotes itself; the value has to bring the command characters.
        ("#import shlex\necho '${shlex.quote(str($free))}'", SHELL_EXEC),
    ],
)
def test_breakout(tmp_path, command, breakout):
    assert high(review(tmp_path, command)).breakout == breakout


def test_nested_shell(tmp_path):
    report = review(tmp_path, "sh -c 'echo ${free}'")
    breakout = {f.rule: f.breakout for f in report.findings}
    # Closing the quotes of `sh -c '...'`, or a command character inside the nested shell.
    assert breakout == {"shell-injection": frozenset("'"), "nested-interpreter": SHELL_EXEC}


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
