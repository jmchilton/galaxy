"""The review of each spec tool reports what its case says."""

import os

import pytest

from galaxy.tool_util.security.spec import (
    load_cases,
    review_problems,
    TOOLS_DIRECTORY,
)

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
