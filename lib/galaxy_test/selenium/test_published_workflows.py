from typing import (
    Any,
)

from .framework import (
    selenium_test,
    SharedStateSeleniumTestCase,
)


class TestPublishedWorkflowsGrid(SharedStateSeleniumTestCase):
    user1_email: str
    user2_email: str
    name_1: str
    name_2: str
    id_1: str
    id_2: str

    @selenium_test
    def test_index(self):
        self.navigate_to_published_workflows()
        self.components.workflows.dropdown(id=self.id_1).wait_for_visible()

    @selenium_test
    def test_run_from_preview_and_import(self):
        self.submit_login(self.user2_email)
        assert not any(self.name_1 in w["name"] for w in self.workflow_populator.index())
        self.workflow_preview_open(self.name_1, tab=self.navigation.workflows.published_tab)
        workflows = self.components.workflows
        workflows.preview_import_button.wait_for_visible()
        self.screenshot("public_workflow_preview")
        workflows.preview_run_button.wait_for_and_click()
        workflow_run = self.components.workflow_run
        workflow_run.run_workflow.wait_for_visible()
        assert f"id={self.id_1}" in self.current_url
        self.screenshot("public_workflow_run_before_import")
        workflow_run.import_button.wait_for_and_click()
        copies = self._wait_on(
            lambda: [w for w in self.workflow_populator.index() if self.name_1 in w["name"]] or None,
            "an imported copy of the public workflow",
            wait_type=self.wait_types.DATABASE_OPERATION,
        )
        assert len(copies) == 1 and copies[0]["id"] != self.id_1, copies

    def setup_shared_state(self):
        self.__class__.user1_email = self._get_random_email("test1")
        self.__class__.user2_email = self._get_random_email("test2")
        self.register(self.user1_email)
        workflow_1 = self._new_public_workflow()
        self.__class__.name_1 = workflow_1["name"]
        self.__class__.id_1 = workflow_1["id"]
        self.logout_if_needed()

        self.register(self.user2_email)
        workflow_2 = self._new_public_workflow()
        self.__class__.name_2 = workflow_2["name"]
        self.__class__.id_2 = workflow_2["id"]
        self.logout_if_needed()

    def _new_public_workflow(self) -> dict[str, Any]:
        name = self._get_random_name()
        contents = self.workflow_populator.load_workflow(name)
        workflow_response = self.workflow_populator.create_workflow_response(contents, publish=True)
        workflow_response.raise_for_status()
        workflow = workflow_response.json()
        return workflow
