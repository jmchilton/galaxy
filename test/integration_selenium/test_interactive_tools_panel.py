from uuid import uuid4

from galaxy.model import InteractiveToolEntryPoint
from galaxy_test.selenium.framework import selenium_test
from ._base_interactive_tools import BaseInteractiveToolsSeleniumIntegration


class TestInteractiveToolsPanelSeleniumIntegration(BaseInteractiveToolsSeleniumIntegration):
    @selenium_test
    def test_interactive_tools_panel_running_and_stop(self):
        name = f"panel entry {uuid4().hex[:8]}"
        job_id, ep_id = self._create_it_job_with_entry_point(name=name)
        self._configure_entry_points(job_id)

        self.home()
        self.interactive_tools_panel_open()
        self.interactive_tool_wait_running(name)
        self.components.interactive_tools_panel.active_tool_open_in_new_tab(name=name).wait_for_visible()
        self.screenshot("interactive_tools_panel_running")

        self.interactive_tool_stop(name)
        ep = self._app.model.context.get(InteractiveToolEntryPoint, ep_id)
        self._app.model.context.refresh(ep)
        assert ep.deleted
