import tempfile
from typing import (
    Callable,
    List,
)
from unittest import SkipTest
from urllib.parse import urlparse

import requests

from galaxy.util.drs import fetch_drs_to_file
from galaxy_test.base.populators import DatasetPopulator
from ._framework import ApiTestCase

CONTENT = "My Cool DRS Data\n"

# DRS expects identical get/post for two main API entrypoints.
HTTP_METHODS: List[Callable[[str], requests.Response]] = [requests.get, requests.post]


class DrsApiTestCase(ApiTestCase):
    def setUp(self):
        super().setUp()
        self.dataset_populator = DatasetPopulator(self.galaxy_interactor)

    def test_service_info(self):
        api_url = f"{self.url}ga4gh/drs/v1/service-info"
        info_response = requests.get(api_url)
        info_response.raise_for_status()

    def test_404_on_private_datsets(self):
        history_id = self.dataset_populator.new_history()
        hda = self.dataset_populator.new_dataset(history_id, content=CONTENT, wait=True)
        dataset_id = hda["id"]
        self.dataset_populator.make_private(history_id=history_id, dataset_id=dataset_id)
        for method in HTTP_METHODS:
            api_url = f"{self.url}ga4gh/drs/v1/objects/{dataset_id}"
            show_response = method(api_url)
            assert show_response.status_code == 403

    def test_public_data_access(self):
        history_id = self.dataset_populator.new_history()
        hda = self.dataset_populator.new_dataset(history_id, content=CONTENT, wait=True)
        dataset_id = hda["id"]
        for method in HTTP_METHODS:
            api_url = f"{self.url}ga4gh/drs/v1/objects/{dataset_id}"
            show_response = method(api_url)
            show_response.raise_for_status()
            response = show_response.json()
            access_methods = response["access_methods"]
            assert len(access_methods) > 0
            access_method = access_methods[0]
            assert access_method["type"].startswith("http")
            access_url = access_method["access_url"]
            url = access_url["url"]
            headers_list = access_url.get("headers") or []
            headers_as_dict = {}
            for header_str in headers_list:
                key, value = header_str.split(": ", 1)
                headers_as_dict[key] = value

            download_response = requests.get(url, headers=headers_as_dict)
            download_response.raise_for_status()
            assert download_response.text == CONTENT

    def test_public_data_access_util_code(self):
        history_id = self.dataset_populator.new_history()
        hda = self.dataset_populator.new_dataset(history_id, content=CONTENT, wait=True)
        dataset_id = hda["id"]
        components = urlparse(self.url)
        netloc = components.netloc
        scheme = components.scheme
        if components.path != "/":
            raise SkipTest("Real DRS cannot be served on Galaxy not hosted at root.")
        drs_uri = f"drs://{netloc}/{dataset_id}"
        force_http = scheme == "http"
        with tempfile.NamedTemporaryFile(prefix="gxtest_drs") as tf:
            fetch_drs_to_file(drs_uri, tf.name, force_http=force_http)
            with open(tf.name) as f:
                assert CONTENT == f.read()

    def test_exception_handling_schema(self):
        history_id = self.dataset_populator.new_history()
        hda = self.dataset_populator.new_dataset(history_id, content=CONTENT, wait=True)
        dataset_id = hda["id"]

        for method in HTTP_METHODS:
            api_url = f"{self.url}ga4gh/drs/v1/objects/{dataset_id}/access/fakeid"
            error_response = method(api_url)
            assert type(error_response.status_code) == int
            assert error_response.status_code == 404
            error_as_dict = error_response.json()
            assert "status_code" in error_as_dict
            assert "msg" in error_as_dict
