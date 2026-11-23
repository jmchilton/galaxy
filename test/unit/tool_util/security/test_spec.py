"""The review of each spec tool reports what its case says."""

import os

import pytest

from galaxy.tool_util.security.codes import (
    DESCRIPTIONS,
    RefusalCode,
)
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
    refusal_codes_markdown,
)
from galaxy.util import galaxy_directory

CASES = load_cases()


@pytest.mark.parametrize("case_id", sorted(CASES))
def test_review(case_id):
    assert review_problems(CASES[case_id]) == []


def test_every_tool_has_a_case():
    assert sorted(os.listdir(TOOLS_DIRECTORY)) == sorted({case.tool for case in CASES.values()})


def test_every_case_has_jobs():
    for case_id, case in CASES.items():
        assert case.green, case_id
        assert bool(case.red) == (case.code is not None), case_id
        assert all(job.expect.rejected for job in case.red), case_id
        assert not any(job.expect.rejected or job.expect.codes for job in case.green), case_id


@pytest.mark.parametrize("code", list(RefusalCode))
def test_every_code_has_red_and_green_jobs(code):
    cases = [case for case in CASES.values() if case.code == code]
    assert any(case.red for case in cases) and any(case.green for case in cases)
    assert DESCRIPTIONS[code]


@pytest.mark.parametrize("code", list(PatternCode))
def test_every_pattern_has_a_case(code):
    assert any(code in case.review.patterns for case in CASES.values())
    assert PATTERN_DESCRIPTIONS[code]


def test_known_bypasses_are_documented_as_such():
    for case_id, case in CASES.items():
        assert case.known_bypass == case.doc.startswith("A known bypass."), case_id


def test_docs_list_the_codes_and_cases():
    path = os.path.join(galaxy_directory(), "doc", "source", "admin", "tool_security_review.md")
    if not os.path.exists(path):
        pytest.skip("Galaxy's docs are not next to this package")
    with open(path) as fh:
        text = fh.read()
    section = text[text.index(BEGIN) : text.index(END) + len(END)] + "\n"
    assert section == refusal_codes_markdown(CASES), "regenerate with python -m galaxy.tool_util.security.spec.docs"
