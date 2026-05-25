"""Unit tests for _WorkItem.sort_key tier ordering.

Item #4 of the polish plan: tier 0 (TES-less / legacy historical, sorted
by Job.id) comes before tier 1 (TES-having, sorted by ToolExecutionState.id),
so the two-space mix is no longer impossible to dependency-order.
"""

from galaxy.workflow.extract import _WorkItem


def _item(sort_key):
    return _WorkItem(sort_key=sort_key, request_payload=None, tool=None)


def test_tier_zero_sorts_before_tier_one():
    # Tier-0 items (TES-less, sorted by Job.id) precede tier-1 items
    # (TES-having, sorted by TES.id) regardless of the numeric ids.
    a = _item((0, 999))
    b = _item((1, 1))
    assert sorted([b, a], key=lambda it: it.sort_key) == [a, b]


def test_within_tier_zero_sorts_by_id_ascending():
    a = _item((0, 5))
    b = _item((0, 1))
    c = _item((0, 3))
    assert [it.sort_key[1] for it in sorted([a, b, c], key=lambda it: it.sort_key)] == [1, 3, 5]


def test_within_tier_one_sorts_by_id_ascending():
    a = _item((1, 5))
    b = _item((1, 1))
    c = _item((1, 3))
    assert [it.sort_key[1] for it in sorted([a, b, c], key=lambda it: it.sort_key)] == [1, 3, 5]


def test_mixed_payload_orders_legacy_then_tes():
    # Realistic mix: one TES-less legacy job + one TR-backed TES item +
    # one job-backed TES item. Legacy first (job.id=100), then tier-1
    # items by TES.id (3, 7).
    legacy = _item((0, 100))
    tr_with_tes = _item((1, 3))
    job_with_tes = _item((1, 7))
    ordered = sorted([job_with_tes, tr_with_tes, legacy], key=lambda it: it.sort_key)
    assert ordered == [legacy, tr_with_tes, job_with_tes]
