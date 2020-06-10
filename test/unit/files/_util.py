"""Utilities for unit test suite for galaxy.files."""
import os
import tempfile

from galaxy.files import (
    ConfiguredFileSources,
    DictFileSourcesUserContext,
)

TEST_USERNAME = "alice"
TEST_EMAIL = "alice@galaxyprojct.org"


def serialize_and_recover(file_sources_o, user_context=None):
    as_dict = file_sources_o.to_dict(for_serialization=True, user_context=user_context)
    file_sources = ConfiguredFileSources.from_dict(as_dict)
    return file_sources


def find_file_a(dir_list):
    for ent in dir_list:
        if ent["class"] == "File" and ent["name"] == "a":
            return ent

    return None


def list_root(file_sources, uri, recursive, user_context=None):
    file_source_pair = file_sources.get_file_source_path(uri)
    file_source = file_source_pair.file_source
    res = file_source.list("/", recursive=recursive, user_context=user_context)
    return res


def user_context_fixture(user_ftp_dir=None):
    user_context = DictFileSourcesUserContext(
        username=TEST_USERNAME,
        email=TEST_EMAIL,
        user_ftp_dir=user_ftp_dir,
        preferences={
            'webdav|password': 'secret1234',
            'dropbox|access_token': os.environ.get('GALAXY_TEST_DROPBOX_ACCESS_TOKEN'),
        }
    )
    return user_context


def assert_realizes_as(file_sources, uri, expected, user_context=None):
    file_source_path = file_sources.get_file_source_path(uri)
    _, temp_name = tempfile.mkstemp()
    file_source_path.file_source.realize_to(file_source_path.path, temp_name, user_context=user_context)
    try:
        with open(temp_name, "r") as f:
            assert f.read() == expected
    finally:
        os.remove(temp_name)
    return temp_name
