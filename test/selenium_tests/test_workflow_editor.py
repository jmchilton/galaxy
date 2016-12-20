from .framework import (
    selenium_test,
    SeleniumTestCase
)


class WorkflowEditorTestCase(SeleniumTestCase):

    ensure_registered = True

    @selenium_test
    def test_build_workflow(self):
        self.workflow_index_open()
        self.click_button_new_workflow()
        form_element = self.driver.find_element_by_css_selector("#center form")
        action = form_element.get_attribute("action")
        assert action.endswith("/workflow/create"), action

        name = self._get_random_name()
        annotation = self._get_random_name()
        self.fill(form_element, {
            'workflow_name': name,
            'workflow_annotation': annotation,
        })
        self.click_submit(form_element)

        element = self.wait_for_selector("#edit-attributes #workflow-name")
        assert name in element.text, element.text
