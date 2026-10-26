import os
from functools import wraps
from urllib.parse import (
    parse_qs,
    urlparse,
)

from galaxy.util.unittest_utils import (
    skip_if_dockstore_down,
    skip_if_workflowhub_down,
)
from .framework import (
    selenium_test,
    SeleniumIntegrationTestCase,
)

TRS_API_URL_DOCKSTORE = "https://dockstore.org/api"
TRS_API_URL_WORKFLOWHUB = "https://workflowhub.eu"
TRS_CONFIG = f"""
- api_url: {TRS_API_URL_DOCKSTORE}
  doc: 'Dockstore is an open platform used by the GA4GH for sharing Docker-based tools
    and workflows.'
  id: dockstore
  label: dockstore
  link_url: https://dockstore.org
- api_url: {TRS_API_URL_WORKFLOWHUB}
  doc: 'WorkflowHub is a registry of scientific workflows.'
  id: workflowhub
  label: workflowhub
  link_url: https://workflowhub.eu
"""
TRS_ID_DOCKSTORE = (
    "workflow/github.com/iwc-workflows/sars-cov-2-pe-illumina-artic-variant-calling/COVID-19-PE-ARTIC-ILLUMINA"
)
TRS_NAME = "sars-cov-2-pe-illumina-artic-variant-calling/COVID-19-PE-ARTIC-ILLUMINA"
TRS_VERSION_DOCKSTORE = "v0.4"
TRS_ID_WORKFLOWHUB = "110"
TRS_VERSION_WORKFLOWHUB = "4"
WORKFLOW_NAME = "COVID-19: variation analysis on ARTIC PE data"
TRS_URL_DOCKSTORE = f"{TRS_API_URL_DOCKSTORE}/ga4gh/trs/v2/tools/%23{TRS_ID_DOCKSTORE}/versions/{TRS_VERSION_DOCKSTORE}"
TRS_URL_WORKFLOWHUB = (
    f"{TRS_API_URL_WORKFLOWHUB}/ga4gh/trs/v2/tools/{TRS_ID_WORKFLOWHUB}/versions/{TRS_VERSION_WORKFLOWHUB}"
)


def with_page_errors(method):
    # A failed TRS request shows up only as an alert in the page while the test times out
    # waiting for something else, so put the alert text into the failure.
    @wraps(method)
    def wrapped_method(self, *args, **kwargs):
        try:
            return method(self, *args, **kwargs)
        except Exception as e:
            alerts = self.execute_script(
                "return Array.from(document.querySelectorAll('.alert-danger'), el => el.innerText);"
            )
            if alerts:
                raise AssertionError(f"{e}\nErrors shown on page: {alerts}") from e
            raise

    return wrapped_method


class TestTrsImport(SeleniumIntegrationTestCase):
    ensure_registered = True

    @classmethod
    def handle_galaxy_config_kwds(cls, config):
        super().handle_galaxy_config_kwds(config)
        trs_config_dir = cls.trs_config_dir()
        os.makedirs(trs_config_dir)
        trs_config_file = os.path.join(trs_config_dir, "trs_config.yml")
        with open(trs_config_file, "w") as trs_config:
            trs_config.write(TRS_CONFIG)
        config["trs_servers_config_file"] = trs_config_file

    @classmethod
    def trs_config_dir(cls):
        return cls.temp_config_dir("trs")

    def _click_wizard_import_button(self) -> None:
        """Wait for the current wizard step to validate before clicking Import."""
        self.components.workflows.import_next_button.wait_for_and_click()

    def _wait_for_import_redirect(self):
        # The client redirects to the workflow list only once the import request returns,
        # which includes the server fetching the workflow from the remote TRS server.
        self.components.workflows.workflows_list.wait_for_visible(wait_type=self.wait_types.SHED_SEARCH)

    def assert_workflow_imported(self, name):
        # surround name with quotes to consider case where name contains colons
        self.workflow_index_search_for(f'"{name}"')
        assert len(self.workflow_card_elements()) == 1, f"workflow ${name} not imported"

    @skip_if_dockstore_down
    def test_import_workflow_by_url_dockstore(self):
        import_url = f"workflows/trs_import?trs_server=dockstore.org&trs_version={TRS_VERSION_DOCKSTORE}&trs_id=%23{TRS_ID_DOCKSTORE}"
        self._import_workflow_by_url(import_url)

    @skip_if_workflowhub_down
    @with_page_errors
    def test_import_workflow_by_url_workflowhub(self):
        import_url = f"workflows/trs_import?trs_server=workflowhub&trs_version={TRS_VERSION_WORKFLOWHUB}&trs_id={TRS_ID_WORKFLOWHUB}"
        self._import_workflow_by_url(import_url)

    def _import_workflow_by_url(self, import_url: str, run_form: bool = False) -> None:
        # Launch links import without a click on the wizard's Import button.
        self.get(import_url)
        if run_form:
            self._wait_on(
                lambda: urlparse(self.current_url).path.endswith("/workflows/run"),
                "the imported workflow's run page",
                wait_type=self.wait_types.SHED_SEARCH,
            )
            run_workflow_id = parse_qs(urlparse(self.current_url).query)["id"][0]
        else:
            self._wait_for_import_redirect()
        self.workflow_index_open()
        self.assert_workflow_imported(WORKFLOW_NAME)
        imported = self.workflow_populator.index()
        assert len(imported) == 1, imported
        if run_form:
            assert run_workflow_id == imported[0]["id"]
        workflow = self.workflow_populator.download_workflow(imported[0]["id"])
        query = parse_qs(urlparse(import_url).query)
        if "trs_url" in query:
            version = urlparse(query["trs_url"][0]).path.rsplit("/", 1)[-1]
        else:
            version = (query.get("trs_version") or query["trs_version_id"])[0]
        assert workflow["source_metadata"]["trs_version_id"] == version

    @skip_if_dockstore_down
    def test_import_by_search_dockstore(self):
        self.go_to_trs_search()
        self.components.trs_search.search.wait_for_and_send_keys("This is the documentation for the workflow.")
        self.components.trs_search.search_result(
            workflow_name="galaxy-workflow-dockstore-example-1"
        ).wait_for_and_click()
        self._click_wizard_import_button()
        self._wait_for_import_redirect()
        self.workflow_index_open()
        self.assert_workflow_imported("Test Workflow")

    @skip_if_dockstore_down
    def test_import_by_organization_search_dockstore(self):
        self.go_to_trs_search()
        self.components.trs_search.search.wait_for_and_send_keys("organization: iwc-workflows")
        self.components.trs_search.search_result(workflow_name=TRS_NAME).wait_for_and_click()
        # Select version from dropdown
        self.components.trs_search.version_select.select_by_visible_text("v0.4")
        self._click_wizard_import_button()
        self._wait_for_import_redirect()
        self.workflow_index_open()
        self.assert_workflow_imported(WORKFLOW_NAME)
        self.components.workflows.trs_icon.wait_for_visible()
        self.screenshot("workflow_imported_via_dockstore_search")

    @skip_if_workflowhub_down
    @with_page_errors
    def test_import_by_search_workflowhub(self):
        self.go_to_trs_search()
        self.components.trs_search.select_server_button.wait_for_and_click()
        self.components.trs_search.select_server(server="workflowhub").wait_for_and_click()
        self.components.trs_search.search.wait_for_and_send_keys(WORKFLOW_NAME)
        self.components.trs_search.search_result(workflow_name=WORKFLOW_NAME).wait_for_and_click()
        self._click_wizard_import_button()
        self._wait_for_import_redirect()
        self.workflow_index_open()
        self.assert_workflow_imported(WORKFLOW_NAME)

    @skip_if_dockstore_down
    def test_import_by_id_dockstore(self):
        self._import_by_id(f"#{TRS_ID_DOCKSTORE}", server="dockstore")

    @skip_if_workflowhub_down
    @with_page_errors
    def test_import_by_id_workflowhub(self):
        self._import_by_id(TRS_ID_WORKFLOWHUB, server="workflowhub")

    @skip_if_dockstore_down
    def test_import_by_trs_url_dockstore(self):
        self._import_by_trs_url(TRS_URL_DOCKSTORE)

    @skip_if_workflowhub_down
    @with_page_errors
    def test_import_by_trs_url_workflowhub(self):
        self._import_by_trs_url(TRS_URL_WORKFLOWHUB)

    @skip_if_dockstore_down
    def test_auto_import_by_trs_url_dockstore(self):
        import_url = f"workflows/trs_import?trs_url={TRS_URL_DOCKSTORE}"
        self._import_workflow_by_url(import_url)

    @skip_if_workflowhub_down
    @with_page_errors
    def test_auto_import_by_trs_url_workflowhub(self):
        import_url = f"workflows/trs_import?trs_url={TRS_URL_WORKFLOWHUB}"
        self._import_workflow_by_url(import_url)

    @skip_if_dockstore_down
    @selenium_test
    def test_auto_import_by_trs_url_run_form_dockstore(self) -> None:
        self._import_workflow_by_url(f"workflows/trs_import?trs_url={TRS_URL_DOCKSTORE}&run_form=true", run_form=True)

    @skip_if_workflowhub_down
    @with_page_errors
    @selenium_test
    def test_auto_import_by_trs_url_run_form_workflowhub(self) -> None:
        self._import_workflow_by_url(f"workflows/trs_import?trs_url={TRS_URL_WORKFLOWHUB}&run_form=true", run_form=True)

    @skip_if_dockstore_down
    @selenium_test
    def test_auto_import_by_trs_version_run_form(self) -> None:
        import_url = f"workflows/trs_import?trs_server=dockstore.org&trs_version={TRS_VERSION_DOCKSTORE}&trs_id=%23{TRS_ID_DOCKSTORE}&run_form=true"
        self._import_workflow_by_url(import_url, run_form=True)

    @skip_if_dockstore_down
    @selenium_test
    def test_auto_import_by_trs_version_id_run_form(self) -> None:
        import_url = f"workflows/trs_import?trs_server=dockstore.org&trs_version_id={TRS_VERSION_DOCKSTORE}&trs_id=%23{TRS_ID_DOCKSTORE}&run_form=true"
        self._import_workflow_by_url(import_url, run_form=True)

    def _import_by_id(self, trs_id, server):
        self.go_to_trs_by_id()
        self.components.trs_import.select_server_button.wait_for_and_click()
        self.components.trs_import.select_server(server=server).wait_for_and_click()
        self.components.trs_import.input.wait_for_and_send_keys(trs_id)
        # Select version from dropdown
        self.components.trs_import.version_select.select_by_visible_text("v0.4")
        self._click_wizard_import_button()
        self._wait_for_import_redirect()
        self.workflow_index_open()
        self.assert_workflow_imported(WORKFLOW_NAME)

    def _import_by_trs_url(self, trs_url):
        self.go_to_trs_by_url()
        self.components.trs_import.url_input.wait_for_and_send_keys(trs_url)
        self._click_wizard_import_button()
        self._wait_for_import_redirect()
        self.workflow_index_open()
        self.assert_workflow_imported(WORKFLOW_NAME)
