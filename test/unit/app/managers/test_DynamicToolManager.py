from galaxy import (
    exceptions,
    model,
)
from galaxy.app_unittest_utils.toolbox_support import BaseToolBoxTestCase
from galaxy.managers.tools import DynamicToolManager
from galaxy.tool_util_models.dynamic_tool_models import DynamicToolCreatePayload


class TestDynamicToolManager(BaseToolBoxTestCase):
    def setUp(self):
        super().setUp()
        # Initialize toolbox
        assert self.toolbox
        self.dynamic_tool_manager = DynamicToolManager(self.app)
        self.app.config.enable_beta_tool_formats = True

    def test_create_tool(self):
        tool_version = "0.1"
        payload = DynamicToolCreatePayload(
            representation={
                "class": "GalaxyTool",
                "name": "Test Tool",
                "version": tool_version,
                "shell_command": "echo 42",
            }
        )
        dynamic_tool = self.dynamic_tool_manager.create_tool(payload)
        assert dynamic_tool.active
        assert dynamic_tool.public
        assert dynamic_tool.tool_format == "GalaxyTool"
        assert dynamic_tool.tool_version == tool_version

    def test_create_tool_no_version(self):
        payload = DynamicToolCreatePayload(
            representation={"class": "GalaxyTool", "name": "Test Tool", "shell_command": "echo 42"}
        )
        with self.assertRaises(ValueError):
            self.dynamic_tool_manager.create_tool(payload)

    def test_create_tool_requires_beta_tool_formats(self):
        self.app.config.enable_beta_tool_formats = False
        payload = DynamicToolCreatePayload(
            representation={
                "class": "GalaxyTool",
                "name": "Test Tool",
                "version": "0.1",
                "shell_command": "echo 42",
            }
        )
        with self.assertRaises(exceptions.ConfigDoesNotAllowException):
            self.dynamic_tool_manager.create_tool(payload)

    def test_ensure_job_owner_can_run_requires_role_for_private_tool(self):
        session = self.app.model.context
        user = model.User(email="no_execute_role@example.com", password="pw")
        session.add(user)
        session.commit()
        job = model.Job()
        job.user = user
        job.dynamic_tool = model.DynamicTool(public=False, active=True)
        with self.assertRaises(exceptions.InsufficientPermissionsException):
            self.dynamic_tool_manager.ensure_job_owner_can_run(job)

    def test_ensure_job_owner_can_run_skips_public_and_static_tools(self):
        for dynamic_tool in (None, model.DynamicTool(public=True, active=True)):
            job = model.Job()
            job.dynamic_tool = dynamic_tool
            self.dynamic_tool_manager.ensure_job_owner_can_run(job)
