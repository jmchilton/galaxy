"""Every rule the review emits is in the rule catalog."""

import os

from galaxy.tool_util.loader_directory import load_tool_sources_from_path
from galaxy.tool_util.security import review_tool_source
from galaxy.tool_util.security.report import (
    CAPABILITY,
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
from galaxy.tool_util.security.spec import TOOLS_DIRECTORY
from galaxy.util import galaxy_directory

FUNCTIONAL_TOOLS = os.path.join(galaxy_directory(), "test", "functional", "tools")


def test_emitted_rules_are_catalogued():
    kinds: dict[str, set[str]] = {}
    where: dict[str, str] = {}
    tools = [load_tool_sources_from_path(d, recursive=True) for d in (TOOLS_DIRECTORY, FUNCTIONAL_TOOLS)]
    for path, tool_source in (tool for found in tools for tool in found):
        for finding in review_tool_source(tool_source).findings:
            kinds.setdefault(finding.rule, set()).add(finding.kind)
            where.setdefault(finding.rule, path)
    assert {rule: where[rule] for rule in kinds if rule not in set(Rule)} == {}
    wrong_kind = {
        rule: found
        for rule, found in kinds.items()
        if found != {VULNERABILITY if rule in VULNERABILITY_RULES else CAPABILITY}
    }
    assert wrong_kind == {}


def test_report_rule_sets_are_catalogued():
    assert {*CODE_CAPABILITIES, *RUNS_TEXT_RULES, SANITIZE_OFF} <= set(Rule)


def test_rules_and_descriptions_match():
    assert set(DESCRIPTIONS) == set(Rule)
    assert all(DESCRIPTIONS.values())
