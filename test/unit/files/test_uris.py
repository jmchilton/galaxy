import ipaddress

import pytest
import responses

from galaxy.exceptions import (
    AdminRequiredException,
    ConfigDoesNotAllowException,
    RequestParameterInvalidException,
)
from galaxy.files.uris import (
    open_validated_url,
    validate_non_local,
    validate_uri_access,
)


@pytest.mark.usefixtures("fake_public_dns")
def test_validate_local_ip_access():
    assert validates_as_non_local("http://google.com", [])
    assert not validates_as_non_local("http://127.0.0.1/secrets.txt", [])
    assert validates_as_non_local("http://127.0.0.1/secrets.txt", [ipaddress.ip_address("127.0.0.1")])
    assert validates_as_non_local("http://127.0.0.1/secrets.txt", [ipaddress.ip_network("127.0.0.0/24")])
    assert not validates_as_non_local("http://127.0.0.1/secrets.txt", [ipaddress.ip_network("127.0.0.0/32")])
    assert validates_as_non_local(
        "http://127.0.0.1/secrets.txt", [ipaddress.ip_network("127.0.0.0/32"), ipaddress.ip_network("127.0.0.1/32")]
    )


@pytest.mark.usefixtures("fake_public_dns")
def test_validate():
    # Check the non local ip address checks from above...
    assert validates("http://google.com", False, [])
    assert not validates("http://127.0.0.1/secrets.txt", False, [])
    assert validates("http://127.0.0.1/secrets.txt", False, [ipaddress.ip_address("127.0.0.1")])
    assert validates("http://127.0.0.1/secrets.txt", False, [ipaddress.ip_network("127.0.0.0/24")])
    assert not validates("http://127.0.0.1/secrets.txt", False, [ipaddress.ip_network("127.0.0.0/32")])
    assert validates(
        "http://127.0.0.1/secrets.txt",
        False,
        [ipaddress.ip_network("127.0.0.0/32"), ipaddress.ip_network("127.0.0.1/32")],
    )

    # check that only admins can acess files...
    assert not validates("file://foo/bar", False, [])
    assert validates("file://foo/bar", True, [])


@pytest.mark.parametrize(
    "bad_url",
    [
        "https://.../SRR1957099.fastq.gz",
        "https://./foo",
        "https://..example.com/x",
        "https:///foo",
        "http:// /foo",
    ],
)
def test_validate_non_local_rejects_malformed_host(bad_url):
    with pytest.raises(RequestParameterInvalidException):
        validate_non_local(bad_url, [])


@pytest.mark.usefixtures("fake_public_dns")
def test_validate_non_local_strips_surrounding_whitespace():
    # Leading whitespace was already tolerated; trailing whitespace used to
    # slip through to getaddrinfo and raise an opaque error.
    assert validates_as_non_local("  http://google.com/x  ", [])
    assert validates_as_non_local("\thttp://google.com/x\n", [])


@pytest.mark.parametrize("bad_url", ["ftp://example.org/a", "https://user:pw@example.org/a", "https:///a"])
def test_open_validated_url_rejects_before_request(bad_url):
    with pytest.raises(RequestParameterInvalidException):
        with open_validated_url(bad_url, []):
            pass


@pytest.mark.usefixtures("fake_public_dns")
@responses.activate
def test_open_validated_url_drops_authorization_on_cross_host_redirect():
    responses.add(responses.GET, "https://a.example.org/1", status=302, headers={"Location": "/2"})
    responses.add(responses.GET, "https://a.example.org/2", status=302, headers={"Location": "https://b.example.org/3"})
    responses.add(responses.GET, "https://b.example.org/3", body="ok")
    with open_validated_url("https://a.example.org/1", [], headers={"Authorization": "x", "X-Other": "y"}) as response:
        assert response.text == "ok"
    sent = [call.request.headers for call in responses.calls]
    assert [h.get("Authorization") for h in sent] == ["x", "x", None]
    assert [h.get("X-Other") for h in sent] == ["y", "y", "y"]


def validates_as_non_local(uri: str, allow_list):
    try:
        validate_non_local(uri, allow_list)
    except ConfigDoesNotAllowException:
        return False
    return True


def validates(uri: str, is_admin, allow_list):
    try:
        validate_uri_access(uri, is_admin, allow_list)
    except (ConfigDoesNotAllowException, AdminRequiredException):
        return False
    return True
