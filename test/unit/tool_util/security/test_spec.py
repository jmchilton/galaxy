"""The spec: each tool's review matches its case, the cases cover the catalogs, and bad cases fail to load."""

import os

import pytest
from pydantic import ValidationError

from galaxy.tool_util.security.classify import Uncheckable
from galaxy.tool_util.security.patterns import (
    DESCRIPTIONS as PATTERN_DESCRIPTIONS,
    PatternCode,
)
from galaxy.tool_util.security.rules import VULNERABILITY_RULES
from galaxy.tool_util.security.spec import (
    FindingExpectation,
    load_cases,
    review_problems,
    ReviewExpectation,
    TOOLS_DIRECTORY,
)
from galaxy.tool_util.security.spec.docs import (
    BEGIN,
    END,
    spec_cases_markdown,
)
from galaxy.util import galaxy_directory

CASES = load_cases()


@pytest.mark.parametrize("case_id", sorted(CASES))
def test_review(case_id):
    assert review_problems(CASES[case_id]) == []


def test_every_tool_has_a_case():
    assert sorted(os.listdir(TOOLS_DIRECTORY)) == sorted({case.tool for case in CASES.values()})


def test_every_case_expects_something():
    for case_id, case in CASES.items():
        review = case.review
        expects = (review.serious_rules, review.unchecked_locations, review.rewrites, review.codes)
        assert review.findings or review.patterns or any(e is not None for e in expects), case_id


def test_every_pattern_has_a_case():
    assert set(PatternCode) - {code for case in CASES.values() for code in case.review.patterns} == set()


def test_patterns_and_descriptions_match():
    assert set(PATTERN_DESCRIPTIONS) == set(PatternCode)
    assert all(PATTERN_DESCRIPTIONS.values())


def test_every_vulnerability_rule_has_a_case():
    assert VULNERABILITY_RULES - {rule for case in CASES.values() for rule in case.review.rules} == set()


def test_spec_rejects_an_unknown_rule():
    with pytest.raises(ValidationError):
        FindingExpectation(rule="shell-injektion")


def test_spec_rejects_an_unknown_severity():
    with pytest.raises(ValidationError):
        FindingExpectation(rule="shell-injection", severity="hihg")


def test_spec_rejects_review_failed_as_a_classify_code():
    with pytest.raises(ValidationError):
        ReviewExpectation(codes=[Uncheckable.REVIEW_FAILED])


def test_docs_list_the_cases():
    path = os.path.join(galaxy_directory(), "doc", "source", "admin", "tool_security_review.md")
    if not os.path.exists(path):
        pytest.skip("Galaxy's docs are not next to this package")
    with open(path) as fh:
        text = fh.read()
    section = text[text.index(BEGIN) : text.index(END) + len(END)] + "\n"
    assert section == spec_cases_markdown(CASES), "regenerate with python -m galaxy.tool_util.security.spec.docs"


def test_spec_files_are_packaged():
    path = os.path.join(galaxy_directory(), "packages", "tool_util", "MANIFEST.in")
    if not os.path.exists(path):
        pytest.skip("Galaxy's packages are not next to this package")
    with open(path) as fh:
        included = {line.split()[1] for line in fh if line.startswith("include ")}
    spec = "src/galaxy/tool_util/security/spec"
    expected = {f"{spec}/cases.yml", *(f"{spec}/tools/{name}" for name in os.listdir(TOOLS_DIRECTORY))}
    assert expected - included == set()
