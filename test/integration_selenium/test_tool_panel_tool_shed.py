from galaxy_test.driver.uses_shed import UsesShed
from .framework import (
    selenium_test,
    SeleniumIntegrationTestCase,
)

COMPOSE_TEXT_PARAM_GUID = "toolshed.g2.bx.psu.edu/repos/iuc/compose_text_param/compose_text_param/0.1.1"


class TestToolPanelWithToolShedTool(SeleniumIntegrationTestCase, UsesShed):
    run_as_admin = True

    @classmethod
    def handle_galaxy_config_kwds(cls, config):
        super().handle_galaxy_config_kwds(config)
        cls.configure_shed(config)

    @selenium_test
    def test_tool_open_by_tool_shed_guid(self):
        self.install_repository("iuc", "compose_text_param", "e188c9826e0f")  # 0.1.1
        self.home()
        # Searches the panel for "id:<full id>" and waits for that tool's link before clicking it.
        self.tool_open(COMPOSE_TEXT_PARAM_GUID)
        self.sleep_for(self.wait_types.UX_RENDER)
        self.screenshot("tool_panel_search_by_tool_shed_id")
