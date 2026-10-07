"""Reusable UI helpers must work without Galaxy's test framework."""

import os
import subprocess
import sys
from pathlib import Path
from unittest.mock import Mock

import pytest

import galaxy.selenium
from galaxy.selenium.navigates_galaxy import NavigatesGalaxy

GALAXY_LIB = Path(galaxy.selenium.__file__).resolve().parents[2]


@pytest.mark.parametrize(
    "module",
    ["galaxy.selenium.upload_activity_helpers"],
)
def test_ui_helpers_import_without_test_framework(module):
    # A fresh interpreter catches transitive imports even when the test runner has already loaded them.
    script = """
import importlib
import importlib.abc
import sys

class NoTestFramework(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname.split(".")[0] in {"galaxy_test", "pytest"}:
            raise ImportError(f"UI helpers must not import {fullname}")

sys.meta_path.insert(0, NoTestFramework())
importlib.import_module(sys.argv[1])
"""
    result = subprocess.run(
        [sys.executable, "-c", script, module],
        env={**os.environ, "PYTHONPATH": str(GALAXY_LIB)},
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr


@pytest.mark.parametrize("expand", [False, True])
def test_workflow_wait_is_available_to_standalone_navigation(expand):
    context = Mock()
    context.wait_length.return_value = 45
    NavigatesGalaxy.workflow_run_wait_for_ok(context, 3, expand=expand)
    context.content_item_by_attributes.assert_called_once_with(hid=3, state="ok")
    item = context.content_item_by_attributes.return_value
    item.wait_for_present.assert_called_once_with(timeout=45)
    assert item.title.wait_for_and_click.call_count == int(expand)
