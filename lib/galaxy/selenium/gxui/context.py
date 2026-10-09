"""The Galaxy context a gxui daemon holds: Galaxy's standalone context plus the task mixins."""

import json
import os
import re
import time
from typing import cast

from galaxy.selenium.context import GalaxySeleniumContextImpl
from galaxy.selenium.has_playwright_driver import HasPlaywrightDriver
from galaxy.selenium.smart_components import SmartTarget
from galaxy.selenium.upload_activity_helpers import UsesUploadActivity
from .config import (
    ConfigError,
    server_url,
)


class GxuiContext(GalaxySeleniumContextImpl, UsesUploadActivity):
    def __init__(self, from_dict: dict, artifacts: str) -> None:
        if state := from_dict.get("storage_state"):
            url = from_dict.get("local_galaxy_url", "http://localhost:8080")
            driver = {**from_dict.get("driver", {}), "storage_state": _saved_state_for(state, url)}
            from_dict = {**from_dict, "driver": driver}
        super().__init__(from_dict)
        self.artifacts = artifacts

    def _screenshot_path(self, label, extension=".png"):
        directory = os.path.join(self.artifacts, "png")
        os.makedirs(directory, exist_ok=True)
        return os.path.join(directory, label + extension)

    def component(self, path: str) -> SmartTarget:
        """A SmartTarget for a navigation.yml path such as ``history_panel.item(hid=3).title``."""
        # The tour grammar takes `key=value` literally; agents naturally quote values.
        path = _QUOTED_ARGUMENT.sub(r"=\2", path)
        try:
            return self.components.resolve_component(path)
        except KeyError as e:
            if e.args == ("_",):
                raise ValueError(
                    f"{path!r} groups other components and has no element of its own; see `gxui components {path}`"
                ) from None
            raise

    def api_get(self, endpoint, data=None, raw=False):
        """Back off and retry when a public server rate-limits (429) instead of failing on its HTML page."""
        for delay in (5, 10, 20, None):
            response = super().api_get(endpoint, data=data, raw=True)
            if response.status_code != 429:
                return self._handle_response(response, raw)
            if delay is None:
                raise RuntimeError(f"the server rate-limited api/{endpoint} (429) for 35s; wait a minute and retry")
            time.sleep(delay)

    def locator(self, target):
        """The Playwright Locator for a Target (first match)."""
        return cast(HasPlaywrightDriver, self._driver_impl).playwright_locator(target.element_locator).first


def _saved_state_for(state: str | dict, url: str) -> dict:
    """A saved login (a path or storage-state dict) without gxui's binding, refused for another Galaxy."""
    if isinstance(state, str):
        with open(state) as handle:
            saved = json.load(handle)
    else:
        saved = dict(state)
    binding = saved.pop("_gxui", None)
    if binding and binding["url"] != server_url(url):
        raise ConfigError("saved login state belongs to a different Galaxy URL")
    return saved


_QUOTED_ARGUMENT = re.compile(r"""=\s*(['"])(.*?)\1""")
