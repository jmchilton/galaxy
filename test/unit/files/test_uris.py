import ipaddress

import pytest
import requests
import responses

from galaxy.exceptions import (
    AdminRequiredException,
    ConfigDoesNotAllowException,
    RequestParameterInvalidException,
)
from galaxy.files.uris import (
    get_checking_every_redirect,
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


@responses.activate
def test_get_checking_every_redirect_checks_each_hop_before_requesting_it():
    responses.get("http://a.test/start", status=302, headers={"Location": "http://b.test/next"})
    responses.get("http://b.test/next", status=302, headers={"Location": "/end"})
    responses.get("http://b.test/end", body=b"done")
    checked = []

    def headers_for(url):
        return {"X-Origin": url.split("/")[2]}

    with get_checking_every_redirect("http://a.test/start", checked.append, headers_for) as response:
        assert response.content == b"done"
    assert checked == ["http://a.test/start", "http://b.test/next", "http://b.test/end"]
    assert [call.request.headers["X-Origin"] for call in responses.calls] == ["a.test", "b.test", "b.test"]

    def refuse_b(url):
        if "b.test" in url:
            raise ConfigDoesNotAllowException()

    with pytest.raises(ConfigDoesNotAllowException):
        with get_checking_every_redirect("http://a.test/start", refuse_b, headers_for):
            pass
    assert len(responses.calls) == 4
    with pytest.raises(requests.exceptions.TooManyRedirects):
        with get_checking_every_redirect("http://a.test/start", checked.append, headers_for, max_redirects=1):
            pass


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
