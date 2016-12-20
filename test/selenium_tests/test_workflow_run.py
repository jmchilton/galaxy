
from .framework import (
    selenium_test,
    SeleniumTestCase
)


class WorkflowRunTestCase(SeleniumTestCase):

    ensure_registered = True

    @selenium_test
    def test_simple_execution(self):
        workflow_populator = self.workflow_populator
        workflow = workflow_populator.load_workflow(name="test_simple_execution")
        self.workflow_populator.create_workflow( workflow )
        self.workflow_index_open()
        self.workflow_index_click_option("Run")
        assert False
