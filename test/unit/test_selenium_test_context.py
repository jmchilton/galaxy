"""Tests for contexts that depend on the Galaxy test framework."""

from unittest.mock import Mock

from galaxy.selenium import driver_factory
from galaxy.selenium.navigates_galaxy import WAIT_TYPES
from galaxy_test.selenium import jupyter_context


def test_jupyter_test_init_from_config(monkeypatch, tmp_path):
    # Keep the test-framework case out of galaxy-selenium's standalone package suite.
    monkeypatch.setattr(driver_factory, "get_playwright_driver", lambda **kwds: Mock())
    monkeypatch.chdir(tmp_path)
    context = jupyter_context.init(
        {"driver": {"backend_type": "playwright", "headless": True}, "timeout_multiplier": 3}
    )
    assert isinstance(context, jupyter_context.JupyterTestContextImpl)
    assert context.wait_length(WAIT_TYPES.UX_RENDER) == WAIT_TYPES.UX_RENDER.default_length * 3
