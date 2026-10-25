import email
import email.message
import io
import os
import urllib.request
import urllib.response
from typing import Any
from unittest import mock

import pytest

from galaxy import exceptions
from ._util import (
    assert_realizes_as,
    assert_realizes_contains,
    configured_file_sources,
    patch_http_open,
    user_context_fixture,
)

SCRIPT_DIRECTORY = os.path.abspath(os.path.dirname(__file__))
FILE_SOURCES_CONF = os.path.join(SCRIPT_DIRECTORY, "http_file_sources_conf.yml")
FILE_SOURCES_CONF_WITHOUT_STOCK = os.path.join(SCRIPT_DIRECTORY, "http_without_stock_file_sources_conf.yml")


@pytest.mark.usefixtures("fake_public_dns")
def test_file_source_http_specific():
    test_url = "https://www.usegalaxy.org/myfile.txt"

    def check_specific_header(request, **kwargs):
        assert request.headers["Authorization"] == "Bearer IBearTokens"
        response: Any = io.StringIO("hello specific world")
        response.headers = {}
        response.geturl = lambda: test_url
        return response

    with patch_http_open(check_specific_header):
        user_context = user_context_fixture()
        file_sources = configured_file_sources(FILE_SOURCES_CONF)
        file_source_pair = file_sources.get_file_source_path(test_url)

        assert file_source_pair.path == test_url
        assert file_source_pair.file_source.id == "test1"

        assert_realizes_as(file_sources, test_url, "hello specific world", user_context=user_context)


@pytest.mark.usefixtures("fake_public_dns")
def test_file_source_another_http_specific():
    test_url = "http://www.galaxyproject.org/anotherfile.txt"

    def check_another_header(request, **kwargs):
        assert request.headers["Another_header"] == "found"
        response: Any = io.StringIO("hello another world")
        response.geturl = lambda: test_url
        response.headers = {}
        return response

    with patch_http_open(check_another_header):
        user_context = user_context_fixture()
        file_sources = configured_file_sources(FILE_SOURCES_CONF)
        file_source_pair = file_sources.get_file_source_path(test_url)

        assert file_source_pair.path == test_url
        assert file_source_pair.file_source.id == "test2"

        assert_realizes_as(file_sources, test_url, "hello another world", user_context=user_context)


@pytest.mark.usefixtures("fake_public_dns")
def test_file_source_http_generic():
    test_url = "https://www.elsewhere.org/myfile.txt"

    def check_generic_headers(request, **kwargs):
        assert not request.headers
        response: Any = io.StringIO("hello generic world")
        response.headers = {}
        response.geturl = lambda: test_url
        return response

    with patch_http_open(check_generic_headers):
        user_context = user_context_fixture()
        file_sources = configured_file_sources(FILE_SOURCES_CONF)
        file_source_pair = file_sources.get_file_source_path(test_url)

        assert file_source_pair.path == test_url
        assert file_source_pair.file_source.id == "test3"

        assert_realizes_as(file_sources, test_url, "hello generic world", user_context=user_context)


def test_file_source_http_leaves_reused_fd_open(tmp_path):
    test_url = "https://www.elsewhere.org/myfile.txt"
    target = tmp_path / "realized"
    sentinel_path = tmp_path / "sentinel"
    sentinel_fds = []
    real_close = os.close

    def close_and_reuse_fd(fd):
        real_close(fd)
        # Another thread opening a file now receives the freed descriptor number.
        sentinel_fds.append(os.open(sentinel_path, os.O_WRONLY | os.O_CREAT))

    def generic_response(request, **kwargs):
        response: Any = io.StringIO("hello generic world")
        response.headers = {}
        response.geturl = lambda: test_url
        return response

    file_sources = configured_file_sources(FILE_SOURCES_CONF)
    file_source_pair = file_sources.get_file_source_path(test_url)
    with (
        patch_http_open(generic_response),
        mock.patch.object(os, "close", new=close_and_reuse_fd),
    ):
        file_source_pair.file_source.realize_to(file_source_pair.path, str(target), user_context=user_context_fixture())

    try:
        for fd in sentinel_fds:
            os.fstat(fd)
    finally:
        for fd in sentinel_fds:
            try:
                real_close(fd)
            except OSError:
                pass
    assert target.read_text() == "hello generic world"


def test_file_source_ftp_url():
    test_url = "ftp://ftp.gnu.org/README"

    def check_generic_headers(request, **kwargs):
        assert not request.headers
        response: Any = io.StringIO("This is ftp.gnu.org, the FTP server of the the GNU project.")
        response.headers = {}
        response.geturl = lambda: test_url
        return response

    with patch_http_open(check_generic_headers):
        user_context = user_context_fixture()
        file_sources = configured_file_sources(FILE_SOURCES_CONF)
        file_source_pair = file_sources.get_file_source_path(test_url)

        assert file_source_pair.path == test_url
        assert file_source_pair.file_source.id == "test3"

        assert_realizes_contains(
            file_sources,
            test_url,
            "This is ftp.gnu.org, the FTP server of the the GNU project.",
            user_context=user_context,
        )


@pytest.mark.usefixtures("fake_public_dns")
def test_file_source_http_validates_redirect_target(tmp_path):
    test_url = "https://www.elsewhere.org/myfile.txt"
    redirect_url = "http://127.0.0.1/myfile.txt"
    requested = []

    def fake_open(handler, req):
        requested.append(req.full_url)
        if req.full_url == test_url:
            response = urllib.response.addinfourl(
                io.BytesIO(b""), email.message_from_string(f"Location: {redirect_url}\n\n"), req.full_url, 302
            )
        else:
            response = urllib.response.addinfourl(io.BytesIO(b"redirected"), email.message.Message(), req.full_url, 200)
        response.msg = "Found" if response.code == 302 else "OK"
        return response

    file_sources = configured_file_sources(FILE_SOURCES_CONF)
    file_source_pair = file_sources.get_file_source_path(test_url)
    with (
        mock.patch.object(urllib.request.HTTPSHandler, "https_open", new=fake_open),
        mock.patch.object(urllib.request.HTTPHandler, "http_open", new=fake_open),
    ):
        with pytest.raises(exceptions.ConfigDoesNotAllowException):
            file_source_pair.file_source.realize_to(
                file_source_pair.path, str(tmp_path / "realized"), user_context=user_context_fixture()
            )
    assert requested == [test_url]


def test_file_source_http_without_stock_generic():
    test_url = "https://www.elsewhere.org/myfile.txt"
    file_sources = configured_file_sources(FILE_SOURCES_CONF_WITHOUT_STOCK)
    with pytest.raises(exceptions.RequestParameterInvalidException, match="Could not find handler for URI"):
        file_sources.get_file_source_path(test_url)


@pytest.mark.usefixtures("fake_public_dns")
def test_file_source_http_without_stock_specific():
    test_url = "https://www.usegalaxy.org/myfile2.txt"

    def check_specific_header(request, **kwargs):
        assert request.headers["Authorization"] == "Bearer IBearTokens"
        response: Any = io.StringIO("hello specific world 2")
        response.headers = {}
        response.geturl = lambda: test_url
        return response

    with patch_http_open(check_specific_header):
        user_context = user_context_fixture()
        file_sources = configured_file_sources(FILE_SOURCES_CONF_WITHOUT_STOCK)
        file_source_pair = file_sources.get_file_source_path(test_url)

        assert file_source_pair.path == test_url
        assert file_source_pair.file_source.id == "test1"

        assert_realizes_as(file_sources, test_url, "hello specific world 2", user_context=user_context)
