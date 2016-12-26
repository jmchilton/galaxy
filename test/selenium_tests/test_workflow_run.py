
from .framework import (
    selenium_test,
    SeleniumTestCase
)


class WorkflowRunTestCase(SeleniumTestCase):

    ensure_registered = True

    @selenium_test
    def test_simple_execution(self):
        workflow_populator = self.workflow_populator
        workflow_populator.upload_yaml_workflow("""
class: GalaxyWorkflow
inputs:
  - id: input1
steps:
  - tool_id: cat
    label: first_cat
    state:
      input1:
        $link: input1
      queries:
        - input2:
            $link: input1
""")
        self.workflow_index_open()
        self.workflow_index_click_option("Run")
        assert False
