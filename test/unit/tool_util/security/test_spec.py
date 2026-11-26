"""The review of each spec tool reports what its case says."""

import os

import pytest

from galaxy.tool_util.security.patterns import (
    DESCRIPTIONS as PATTERN_DESCRIPTIONS,
    PatternCode,
)
from galaxy.tool_util.security.spec import (
    load_cases,
    review_problems,
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
        expects = (review.serious_rules, review.unchecked_locations, review.rewrites)
        assert review.findings or review.patterns or any(e is not None for e in expects), case_id


@pytest.mark.parametrize("code", list(PatternCode))
def test_every_pattern_has_a_case(code):
    assert any(code in case.review.patterns for case in CASES.values())
    assert PATTERN_DESCRIPTIONS[code]


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
