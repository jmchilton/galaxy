"""Apply integration CI selection before assigning whole groups to shards."""

import os

import pytest

from galaxy_test import shard
from galaxy_test.integration_selection import (
    FAMILIES,
    selected_families,
)


def deselect_unaffected(config: pytest.Config, items: list[pytest.Item]) -> None:
    """Run before cost-based sharding and before any fixture or setUpClass."""
    families = selected_families(os.environ)
    if families is None or families == FAMILIES:
        return
    selected, deselected = [], []
    for item in items:
        markers = list(item.iter_markers("ci_integration_family"))
        # Inherited class/module marks describe additional dependencies. Retain a
        # test if any family changed; unknown or malformed marks stay unconditional.
        required = set()
        for marker in markers:
            if len(marker.args) != 1 or not isinstance(marker.args[0], str) or marker.args[0] not in FAMILIES:
                break
            required.add(marker.args[0])
        else:
            if required and required.isdisjoint(families):
                deselected.append(item)
                continue
        selected.append(item)
    if deselected:
        config.hook.pytest_deselected(items=deselected)
        items[:] = selected


@pytest.hookimpl(trylast=True)
def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    deselect_unaffected(config, items)
    shard.pytest_collection_modifyitems(config, items)
