"""Basis for Selenium test framework."""
from __future__ import absolute_import
from __future__ import print_function

import datetime
import json
import os

from functools import wraps

import requests

from galaxy_selenium import (
    driver_factory,
)
from galaxy_selenium.navigates_galaxy import NavigatesGalaxy

try:
    from pyvirtualdisplay import Display
except ImportError:
    Display = None

from six.moves.urllib.parse import urljoin

from base import populators
from base.driver_util import classproperty, DEFAULT_WEB_HOST, get_ip_address
from base.twilltestcase import FunctionalTestCase
from base.workflows_format_2 import (
    ImporterGalaxyInterface,
    convert_and_import_workflow,
)

from galaxy.util import asbool

DEFAULT_WAIT_TIMEOUT = 15
DEFAULT_TEST_ERRORS_DIRECTORY = os.path.abspath("database/test_errors")
DEFAULT_SELENIUM_BROWSER = "auto"
DEFAULT_SELENIUM_REMOTE = False
DEFAULT_SELENIUM_REMOTE_PORT = "4444"
DEFAULT_SELENIUM_REMOTE_HOST = "127.0.0.1"
DEFAULT_SELENIUM_HEADLESS = "auto"

GALAXY_TEST_ERRORS_DIRECTORY = os.environ.get("GALAXY_TEST_ERRORS_DIRECTORY", DEFAULT_TEST_ERRORS_DIRECTORY)
# Test browser can be ["CHROME", "FIREFOX", "OPERA", "PHANTOMJS"]
GALAXY_TEST_SELENIUM_BROWSER = os.environ.get("GALAXY_TEST_SELENIUM_BROWSER", DEFAULT_SELENIUM_BROWSER)
GALAXY_TEST_SELENIUM_REMOTE = os.environ.get("GALAXY_TEST_SELENIUM_REMOTE", DEFAULT_SELENIUM_REMOTE)
GALAXY_TEST_SELENIUM_REMOTE_PORT = os.environ.get("GALAXY_TEST_SELENIUM_REMOTE_PORT", DEFAULT_SELENIUM_REMOTE_PORT)
GALAXY_TEST_SELENIUM_REMOTE_HOST = os.environ.get("GALAXY_TEST_SELENIUM_REMOTE_HOST", DEFAULT_SELENIUM_REMOTE_HOST)
GALAXY_TEST_SELENIUM_HEADLESS = os.environ.get("GALAXY_TEST_SELENIUM_HEADLESS", DEFAULT_SELENIUM_HEADLESS)
GALAXY_TEST_EXTERNAL_FROM_SELENIUM = os.environ.get("GALAXY_TEST_EXTERNAL_FROM_SELENIUM", None)

# Test case data
DEFAULT_PASSWORD = '123456'


try:
    from nose.tools import nottest
except ImportError:
    def nottest(x):
        return x


@nottest
def selenium_test(f):

    @wraps(f)
    def func_wrapper(self, *args, **kwds):
        try:
            return f(self, *args, **kwds)
        except Exception:
            if GALAXY_TEST_ERRORS_DIRECTORY and GALAXY_TEST_ERRORS_DIRECTORY != "0":
                if not os.path.exists(GALAXY_TEST_ERRORS_DIRECTORY):
                    os.makedirs(GALAXY_TEST_ERRORS_DIRECTORY)
                result_name = f.__name__ + datetime.datetime.now().strftime("%Y%m%d%H%M%s")
                target_directory = os.path.join(GALAXY_TEST_ERRORS_DIRECTORY, result_name)
                os.makedirs(target_directory)
                self.driver.save_screenshot(os.path.join(target_directory, "last.png"))
            raise

    return func_wrapper


class SeleniumTestCase(FunctionalTestCase, NavigatesGalaxy):

    framework_tool_and_types = True
    ensure_registered = False

    def setUp(self):
        super(SeleniumTestCase, self).setUp()
        # Deal with the case when Galaxy has a different URL when being accessed by Selenium
        # then when being accessed by local API calls.
        if GALAXY_TEST_EXTERNAL_FROM_SELENIUM is not None:
            self.target_url_from_selenium = GALAXY_TEST_EXTERNAL_FROM_SELENIUM
        else:
            self.target_url_from_selenium = self.url
        self.display = driver_factory.virtual_display_if_enabled(headless_selenium())
        self.driver = get_driver()

        if self.ensure_registered:
            self.register()

    def tearDown(self):
        exception = None
        try:
            super(SeleniumTestCase, self).tearDown()
        except Exception as e:
            exception = e

        try:
            self.driver.close()
        except Exception as e:
            exception = e

        try:
            self.display.stop()
        except Exception as e:
            exception = e

        if exception is not None:
            raise exception

    @classproperty
    def default_web_host(cls):
        return default_web_host_for_selenium_tests()

    @property
    def default_timeout(self):
        return DEFAULT_WAIT_TIMEOUT

    def build_url(self, url, for_selenium=True):
        if for_selenium:
            base = self.target_url_from_selenium
        else:
            base = self.url
        return urljoin(base, url)

    @property
    def test_data(self):
        return self.navigation_data

    def assert_initial_history_panel_state_correct(self):
        # Move into a TestsHistoryPanel mixin
        unnamed_name = self.test_data["historyPanel"]["text"]["history"]["newName"]

        name_element = self.history_panel_name_element()
        assert name_element.is_displayed()
        assert unnamed_name in name_element.text

        size_selector = self.test_data["historyPanel"]["selectors"]["history"]["size"]
        initial_size_str = self.test_data["historyPanel"]["text"]["history"]["newSize"]

        size_element = self.wait_for_selector(size_selector)
        assert size_element.is_displayed()
        assert initial_size_str in size_element.text, "%s not in %s" % (initial_size_str, size_element.text)

        empty_msg_selector = self.test_data["historyPanel"]["selectors"]["history"]["emptyMsg"]
        empty_msg_str = self.test_data["historyPanel"]["text"]["history"]["emptyMsg"]

        empty_msg_element = self.wait_for_selector(empty_msg_selector)
        assert empty_msg_element.is_displayed()
        assert empty_msg_str in empty_msg_element.text

    @property
    def workflow_populator(self):
        return SeleniumSessionWorkflowPopulator(self)


def default_web_host_for_selenium_tests():
    if asbool(GALAXY_TEST_SELENIUM_REMOTE):
        try:
            dev_ip = get_ip_address('docker0')
            return dev_ip
        except IOError:
            return DEFAULT_WEB_HOST
    else:
        return DEFAULT_WEB_HOST


def get_driver():
    if asbool(GALAXY_TEST_SELENIUM_REMOTE):
        return get_remote_driver()
    else:
        return get_local_driver()


def headless_selenium():
    if asbool(GALAXY_TEST_SELENIUM_REMOTE):
        return False

    if GALAXY_TEST_SELENIUM_HEADLESS == "auto":
        if driver_factory.is_virtual_display_available():
            return True
        else:
            return False
    else:
        return asbool(GALAXY_TEST_SELENIUM_HEADLESS)


def get_local_driver():
    return driver_factory.get_local_driver(GALAXY_TEST_SELENIUM_BROWSER)


def get_remote_driver():
    return driver_factory.get_remote_driver(
        host=GALAXY_TEST_SELENIUM_REMOTE_HOST,
        port=GALAXY_TEST_SELENIUM_REMOTE_PORT,
        browser=GALAXY_TEST_SELENIUM_BROWSER,
    )


class SeleniumSessionGetPostMixin:
    """Mixin for adapting Galaxy testing populators helpers to Selenium session backed bioblend."""

    def _get(self, route):
        return self.selenium_test_case.api_get(route)

    def _post(self, route, data={}):
        full_url = self.selenium_test_case.build_url("api/" + route, for_selenium=False)
        response = requests.post(full_url, data=data, cookies=self.selenium_test_case.selenium_to_requests_cookies())
        return response

    def __url(self, route):
        return self._gi.url + "/" + route


class SeleniumSessionDatasetPopulator(populators.BaseDatasetPopulator, SeleniumSessionGetPostMixin):

    """Implementation of BaseDatasetPopulator backed by bioblend."""

    def __init__(self, selenium_test_case):
        """Construct a dataset populator from a bioblend GalaxyInstance."""
        self.selenium_test_case = selenium_test_case


class SeleniumSessionDatasetCollectionPopulator(populators.BaseDatasetCollectionPopulator, SeleniumSessionGetPostMixin):

    """Implementation of BaseDatasetCollectionPopulator backed by bioblend."""

    def __init__(self, selenium_test_case):
        """Construct a dataset collection populator from a bioblend GalaxyInstance."""
        self.selenium_test_case = selenium_test_case
        self.dataset_populator = SeleniumSessionDatasetPopulator(selenium_test_case)

    def _create_collection(self, payload):
        create_response = self._post( "dataset_collections", data=payload )
        return create_response


class SeleniumSessionWorkflowPopulator(populators.BaseWorkflowPopulator, SeleniumSessionGetPostMixin, ImporterGalaxyInterface):

    """Implementation of BaseWorkflowPopulator backed by bioblend."""

    def __init__(self, selenium_test_case):
        """Construct a workflow populator from a bioblend GalaxyInstance."""
        self.selenium_test_case = selenium_test_case
        self.dataset_populator = SeleniumSessionDatasetPopulator(selenium_test_case)

    def import_workflow(self, workflow, **kwds):
        workflow_str = json.dumps(workflow, indent=4)
        data = {
            'workflow': workflow_str,
        }
        data.update(**kwds)
        upload_response = self._post("workflows", data=data)
        assert upload_response.status_code == 200
        return upload_response.json()

    def upload_yaml_workflow(self, has_yaml, **kwds):
        workflow = convert_and_import_workflow(has_yaml, galaxy_interface=self, **kwds)
        return workflow[ "id" ]
