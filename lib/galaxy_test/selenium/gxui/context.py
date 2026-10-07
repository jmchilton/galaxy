"""The Galaxy context a gxui daemon holds: Galaxy's standalone context plus the task mixins."""

import os
import re
from typing import cast

from galaxy.selenium.context import GalaxySeleniumContextImpl
from galaxy.selenium.has_playwright_driver import HasPlaywrightDriver
from galaxy.selenium.smart_components import SmartTarget
from galaxy_test.selenium.framework import RunsWorkflows
from galaxy_test.selenium.upload_activity_helpers import UsesUploadActivity


class GxuiContext(GalaxySeleniumContextImpl, RunsWorkflows, UsesUploadActivity):
    def __init__(self, from_dict: dict, artifacts: str) -> None:
        super().__init__(from_dict)
        self.artifacts = artifacts
        self.login_email = from_dict.get("login_email")
        self.login_password = from_dict.get("login_password")

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

    def locator(self, target):
        """The Playwright Locator for a Target (first match)."""
        return cast(HasPlaywrightDriver, self._driver_impl).playwright_locator(target.element_locator).first


_QUOTED_ARGUMENT = re.compile(r"""=\s*(['"])(.*?)\1""")
