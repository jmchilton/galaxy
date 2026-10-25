import gzip
from typing import cast
from unittest import mock

import pytest
import responses
from requests import Response

from galaxy.exceptions import ConfigDoesNotAllowException
from galaxy.files.sources.cbioportal import CBioPortalFilesSource


@pytest.mark.usefixtures("fake_public_dns")
@responses.activate
def test_cbioportal_streams_download_and_closes_response(tmp_path):
    url = "https://example.com/study.tar.gz"
    responses.add(
        responses.GET,
        url,
        body=gzip.compress(b"archive contents", mtime=0),
        headers={"Content-Encoding": "gzip"},
    )
    source = object.__new__(CBioPortalFilesSource)
    target = tmp_path / "study.tar.gz"

    with mock.patch.object(CBioPortalFilesSource, "_allowlist", new_callable=mock.PropertyMock, return_value=[]):
        source._stream_url_to_file(url, str(target))

    assert target.read_bytes() == b"archive contents"
    response = cast(Response, responses.calls[0].response)
    assert response.raw.closed


@pytest.mark.usefixtures("fake_public_dns")
@responses.activate
def test_cbioportal_validates_redirect_before_request(tmp_path):
    url = "https://example.com/study.tar.gz"
    responses.add(responses.GET, url, status=302, headers={"Location": "http://127.0.0.1/private"})
    responses.add(responses.GET, "http://127.0.0.1/private", body="private data")
    source = object.__new__(CBioPortalFilesSource)

    with (
        mock.patch.object(CBioPortalFilesSource, "_allowlist", new_callable=mock.PropertyMock, return_value=[]),
        pytest.raises(ConfigDoesNotAllowException),
    ):
        source._stream_url_to_file(url, str(tmp_path / "study.tar.gz"))
    assert [call.request.url for call in responses.calls] == [url]
