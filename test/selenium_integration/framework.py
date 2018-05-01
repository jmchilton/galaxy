from base import integration_util
from selenium_tests import framework


class SeleniumIntegrationTestCase(integration_util.IntegrationTestCase, framework.TestWithSeleniumMixin):

    def setUp(self):
        super(SeleniumIntegrationTestCase, self).setUp()
        self.setup_selenium()

    def tearDown(self):
        self.tear_down_selenium()
        super(SeleniumIntegrationTestCase, self).tearDown()
