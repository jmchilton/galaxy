"""Every rule the review emits is in the rule catalog."""

import os

import pytest
from pydantic import ValidationError

from galaxy.tool_util.loader_directory import load_tool_sources_from_path
from galaxy.tool_util.security import review_tool_source
from galaxy.tool_util.security.report import (
    CODE_CAPABILITIES,
    RUNS_TEXT_RULES,
    SANITIZE_OFF,
    VULNERABILITY,
)
from galaxy.tool_util.security.rules import (
    DESCRIPTIONS,
    Rule,
    VULNERABILITY_RULES,
)
from galaxy.tool_util.security.spec import (
    FindingExpectation,
    load_cases,
    TOOLS_DIRECTORY,
)
from galaxy.util import galaxy_directory

FUNCTIONAL_TOOLS = os.path.join(galaxy_directory(), "test", "functional", "tools")


def test_emitted_rules_are_catalogued():
    emitted = {}
    tools = [load_tool_sources_from_path(d, recursive=True) for d in (TOOLS_DIRECTORY, FUNCTIONAL_TOOLS)]
    for path, tool_source in (tool for found in tools for tool in found):
        for finding in review_tool_source(tool_source).findings:
            emitted.setdefault(finding.rule, (finding.kind, path))
    unknown = {rule: where for rule, where in emitted.items() if rule not in set(Rule)}
    assert unknown == {}
    wrong_kind = [
        rule for rule, (kind, _) in emitted.items() if (kind == VULNERABILITY) != (rule in VULNERABILITY_RULES)
    ]
    assert wrong_kind == []


def test_report_rule_sets_are_catalogued():
    assert {*CODE_CAPABILITIES, *RUNS_TEXT_RULES, SANITIZE_OFF} <= set(Rule)


@pytest.mark.parametrize("rule", list(Rule))
def test_every_rule_has_a_description(rule):
    assert DESCRIPTIONS[rule]


@pytest.mark.parametrize("rule", sorted(VULNERABILITY_RULES))
def test_every_vulnerability_rule_has_a_spec_case(rule):
    cases = load_cases().values()
    assert any(
        rule in (case.review.serious_rules or []) or any(want.rule == rule for want in case.review.findings)
        for case in cases
    )


def test_spec_rejects_an_unknown_rule():
    with pytest.raises(ValidationError):
        FindingExpectation(rule="shell-injektion")
