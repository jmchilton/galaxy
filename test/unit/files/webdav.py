import os

import pytest

from galaxy.datatypes import sniff
from galaxy.files import ConfiguredFileSources, ConfiguredFileSourcesConfig

from ._util import (
    find_file_a,
    list_root,
    serialize_and_recover,
    user_context_fixture,
)

SCRIPT_DIRECTORY = os.path.abspath(os.path.dirname(__file__))
FILE_SOURCES_CONF = os.path.join(SCRIPT_DIRECTORY, "webdav_file_sources_conf.yml")
USER_FILE_SOURCES_CONF = os.path.join(SCRIPT_DIRECTORY, "webdav_user_file_sources_conf.yml")

skip_if_no_webdav = pytest.mark.skipif(
    not os.environ.get('GALAXY_TEST_WEBDAV'),
    reason="GALAXY_TEST_WEBDAV not set"
)


@skip_if_no_webdav
def test_file_source():
    file_sources = _configured_file_sources()
    file_source_pair = file_sources.get_file_source_path("gxfiles://test1")

    assert file_source_pair.path == "/"
    file_source = file_source_pair.file_source
    res = file_source.list("/", recursive=True)
    a_file = find_file_a(res)
    assert a_file
    assert a_file["uri"] == "gxfiles://test1/a", a_file

    res = file_source.list("/", recursive=False)
    assert find_file_a(res)


@skip_if_no_webdav
def test_sniff_to_tmp():
    file_sources = _configured_file_sources()
    _download_and_check_file(file_sources)


@skip_if_no_webdav
def test_serialization():
    # serialize the configured file sources and rematerialize them,
    # ensure they still function. This is needed for uploading files.
    file_sources = serialize_and_recover(_configured_file_sources())

    res = list_root(file_sources, "gxfiles://test1", recursive=True)
    assert find_file_a(res)

    res = list_root(file_sources, "gxfiles://test1", recursive=False)
    assert find_file_a(res)

    _download_and_check_file(file_sources)


@skip_if_no_webdav
def test_serialization_user():
    file_sources_o = _configured_file_sources(USER_FILE_SOURCES_CONF)
    user_context = user_context_fixture()

    res = list_root(file_sources_o, "gxfiles://test1", recursive=True, user_context=user_context)
    assert find_file_a(res)

    file_sources = serialize_and_recover(file_sources_o, user_context=user_context)


def _configured_file_sources(conf_file=FILE_SOURCES_CONF):
    file_sources_config = ConfiguredFileSourcesConfig()
    return ConfiguredFileSources(file_sources_config, conf_file=conf_file)


def _download_and_check_file(file_sources):
    tmp_name = sniff.stream_url_to_file("gxfiles://test1/a", file_sources=file_sources)
    try:
        a_contents = open(tmp_name, "r").read()
        assert a_contents == "a\n"
    finally:
        os.remove(tmp_name)
