"""Fixtures for a version of API testing that relies more heavily on pytest injection."""

import os
from dataclasses import dataclass
from typing import (
    Any,
    Iterator,
    Optional,
)

import pytest

from galaxy.tool_util.verify.test_data import TestDataResolver
from galaxy_test.base.api import (
    AnonymousGalaxyInteractor,
    ApiTestInteractor,
)
from galaxy_test.base.api_util import (
    get_admin_api_key,
    get_user_api_key,
)
from galaxy_test.base.env import setup_keep_outdir
from galaxy_test.base.populators import (
    _raise_skip_if,
    DatasetPopulator,
    get_tool_ids,
    TargetHistory,
)
from galaxy_test.base.testcase import host_port_and_url


@dataclass
class ApiConfigObject:
    host: str
    port: Optional[str]
    url: str
    user_api_key: Optional[str]
    admin_api_key: Optional[str]
    test_data_resolver: Any
    keepOutdir: Any


@pytest.fixture(scope="session")
def api_test_config_object(real_driver) -> ApiConfigObject:
    host, port, url = host_port_and_url(real_driver)
    user_api_key = get_user_api_key()
    admin_api_key = get_admin_api_key()
    test_data_resolver = TestDataResolver()
    keepOutdir = setup_keep_outdir()
    return ApiConfigObject(
        host,
        port,
        url,
        user_api_key,
        admin_api_key,
        test_data_resolver,
        keepOutdir,
    )


@pytest.fixture(scope="session")
def galaxy_interactor(api_test_config_object: ApiConfigObject) -> ApiTestInteractor:
    return ApiTestInteractor(api_test_config_object)


@pytest.fixture(scope="session")
def dataset_populator(galaxy_interactor: ApiTestInteractor) -> DatasetPopulator:
    return DatasetPopulator(galaxy_interactor)


@pytest.fixture(scope="session")
def anonymous_galaxy_interactor(api_test_config_object: ApiConfigObject) -> Iterator[AnonymousGalaxyInteractor]:
    return AnonymousGalaxyInteractor(api_test_config_object)


_celery_app = None
_celery_worker = None


@pytest.fixture(autouse=True, scope="session")
def request_celery_app(celery_session_app, celery_config):
    try:
        global _celery_app
        _celery_app = celery_session_app
        yield
    finally:
        if os.environ.get("GALAXY_TEST_EXTERNAL") is None:
            from galaxy.celery import celery_app

            celery_app.fork_pool.stop()
            celery_app.fork_pool.join(timeout=5)


@pytest.fixture(autouse=True, scope="session")
def request_celery_worker(celery_session_worker, celery_config, celery_worker_parameters):
    global _celery_worker
    _celery_worker = celery_session_worker


@pytest.fixture(scope="session", autouse=True)
def celery_worker_parameters():
    return {
        "queues": ("galaxy.internal", "galaxy.external"),
    }


@pytest.fixture(scope="session")
def celery_parameters():
    return {
        "task_create_missing_queues": True,
        "task_default_queue": "galaxy.internal",
    }


@pytest.fixture
def history_id(dataset_populator: DatasetPopulator, request) -> Iterator[str]:
    history_name = f"API Test History for {request.node.nodeid}"
    with dataset_populator.test_history(name=history_name) as history_id:
        yield history_id


@pytest.fixture
def target_history(dataset_populator: DatasetPopulator, history_id: str) -> TargetHistory:
    return TargetHistory(dataset_populator, history_id)


@pytest.fixture(autouse=True)
def check_required_tools(anonymous_galaxy_interactor, request):
    for marker in request.node.iter_markers():
        if marker.name == "requires_tool_id":
            tool_id = marker.args[0]
            _raise_skip_if(tool_id not in get_tool_ids(anonymous_galaxy_interactor))
