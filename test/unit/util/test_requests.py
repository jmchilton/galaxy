import gzip
import socket
import threading
import time
import uuid

import pytest
import responses
from beaker.cache import CacheManager
from requests.adapters import HTTPAdapter

from galaxy.util import requests as galaxy_requests
from galaxy.util.requests import DEFAULT_RETRIES
from galaxy.util.user_agent import get_default_headers

EXPECTED_USER_AGENT = get_default_headers()["user-agent"]


# --- User-Agent header injection ---


@pytest.mark.parametrize("method", ("delete", "get", "head", "options", "patch", "post", "put"))
@responses.activate
def test_user_agent_and_caller_headers_are_set(method: str):
    """All methods inject the Galaxy user-agent and preserve caller-supplied headers."""
    responses.add(getattr(responses, method.upper()), "https://example.com/", status=200)
    getattr(galaxy_requests, method)("https://example.com/", headers={"X-Custom": "value"})
    req_headers = responses.calls[0].request.headers
    assert req_headers["user-agent"] == EXPECTED_USER_AGENT
    assert req_headers["X-Custom"] == "value"


# --- Session factory ---


@pytest.mark.parametrize("method", (galaxy_requests.Session, galaxy_requests.session))
def test_Session_has_user_agent_header(method):
    s: galaxy_requests.Session = method()
    assert s.headers["user-agent"] == EXPECTED_USER_AGENT


def test_Session_has_no_retry_adapter():
    s = galaxy_requests.Session()
    for url in ("https://example.com/", "http://example.com/"):
        adapter = s.get_adapter(url)
        assert isinstance(adapter, HTTPAdapter)
        assert adapter.max_retries.total == 0  # requests default: no retries


# --- RetrySession ---


def test_RetrySession_has_user_agent_header():
    s = galaxy_requests.RetrySession()
    assert s.headers["user-agent"] == EXPECTED_USER_AGENT


def test_retry_session_has_retry_adapter():
    s = galaxy_requests.RetrySession()
    for url in ("https://example.com/", "http://example.com/"):
        adapter = s.get_adapter(url)
        assert isinstance(adapter, HTTPAdapter)
        assert adapter.max_retries.total == DEFAULT_RETRIES


# --- Retry behaviour ---


@pytest.fixture()
def connection_reset_server():
    """A TCP server that accepts connections and immediately closes them."""
    attempts = 0
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    sock.listen(10)
    stop = threading.Event()
    sock.settimeout(0.1)

    def serve():
        nonlocal attempts
        while not stop.is_set():
            try:
                conn, _ = sock.accept()
            except socket.timeout:  # noqa: UP041  # Python <=3.9 support, replace with TimeoutError in Python 3.10+
                continue
            except OSError:
                break
            attempts += 1
            conn.close()

    thread = threading.Thread(target=serve, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{port}", lambda: attempts
    stop.set()
    sock.close()
    thread.join()


@pytest.mark.parametrize("method", ("delete", "get", "head", "options", "put"))
def test_RetrySession_retries_idempotent_methods(method: str, connection_reset_server):
    """RetrySession retries idempotent methods on connection failure."""
    url, get_attempts = connection_reset_server
    with galaxy_requests.RetrySession() as s:
        with pytest.raises(galaxy_requests.exceptions.ConnectionError):
            getattr(s, method)(url)
    assert get_attempts() == 1 + DEFAULT_RETRIES


@responses.activate
def test_bounded_get_raises_for_error_status():
    responses.add(responses.GET, "https://example.com/a", status=404)
    with pytest.raises(galaxy_requests.exceptions.HTTPError):
        galaxy_requests.bounded_get("https://example.com/a")


@responses.activate
def test_bounded_get_follows_validated_redirects():
    responses.add(responses.GET, "https://example.com/a", status=302, headers={"Location": "/b"})
    responses.add(responses.GET, "https://example.com/b", status=302, headers={"Location": "https://other.org/c"})
    responses.add(responses.GET, "https://other.org/c", body="done")
    validated = []
    assert galaxy_requests.bounded_get("https://example.com/a", validate_url=validated.append) == "done"
    assert validated == ["https://example.com/a", "https://example.com/b", "https://other.org/c"]


@responses.activate
def test_bounded_get_rejected_redirect_is_not_requested():
    responses.add(responses.GET, "https://example.com/a", status=302, headers={"Location": "https://internal/"})

    def validate(url):
        if "internal" in url:
            raise ValueError(url)

    with pytest.raises(ValueError):
        galaxy_requests.bounded_get("https://example.com/a", validate_url=validate)
    assert len(responses.calls) == 1


@responses.activate
def test_bounded_get_rejects_disallowed_scheme_on_redirect():
    responses.add(responses.GET, "https://example.com/a", status=302, headers={"Location": "http://example.com/b"})
    with pytest.raises(galaxy_requests.BoundedFetchError):
        galaxy_requests.bounded_get("https://example.com/a")
    assert len(responses.calls) == 1


@responses.activate
def test_bounded_get_limits_redirects():
    responses.add(responses.GET, "https://example.com/a", status=302, headers={"Location": "/a"})
    with pytest.raises(galaxy_requests.BoundedFetchError):
        galaxy_requests.bounded_get("https://example.com/a", max_redirects=2)
    assert len(responses.calls) == 3


@responses.activate
def test_bounded_get_limits_size():
    responses.add(responses.GET, "https://example.com/a", body="x" * 101)
    with pytest.raises(galaxy_requests.BoundedFetchError):
        galaxy_requests.bounded_get("https://example.com/a", max_bytes=100)


@responses.activate
def test_bounded_get_enforces_total_deadline_across_redirects(monkeypatch):
    responses.add(responses.GET, "https://example.com/a", status=302, headers={"Location": "/b"})
    responses.add(responses.GET, "https://example.com/b", body="late")
    clock = iter(range(0, 1000, 6))
    monkeypatch.setattr(galaxy_requests.time, "monotonic", lambda: float(next(clock)))
    with pytest.raises(galaxy_requests.BoundedFetchError):
        galaxy_requests.bounded_get("https://example.com/a", timeout=10)
    assert len(responses.calls) == 1


@responses.activate
def test_bounded_get_normalizes_urls():
    responses.add(responses.GET, "https://example.com/a", status=302, headers={"Location": "HTTPS://example.com/b"})
    responses.add(responses.GET, "https://example.com/b", body="done")
    validated = []
    assert galaxy_requests.bounded_get("HTTPS://example.com/a", validate_url=validated.append) == "done"
    assert validated == ["https://example.com/a", "https://example.com/b"]


@responses.activate
def test_bounded_get_defaults_to_utf8():
    responses.add(responses.GET, "https://example.com/a", body="Jörg".encode(), content_type="application/x-bibtex")
    assert galaxy_requests.bounded_get("https://example.com/a") == "Jörg"


@responses.activate
def test_bounded_get_uses_declared_charset():
    responses.add(
        responses.GET,
        "https://example.com/a",
        body="Jörg".encode("iso-8859-1"),
        content_type="text/plain; charset=iso-8859-1",
    )
    assert galaxy_requests.bounded_get("https://example.com/a") == "Jörg"


@pytest.fixture()
def slow_http_server():
    """Factory for a one-connection server that sends ``head``, then ``trickle`` one byte every 0.2 seconds."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    sock.listen(1)
    stop = threading.Event()
    threads = []

    def serve(head: bytes, trickle: bytes):
        conn, _ = sock.accept()
        with conn:
            conn.recv(4096)
            conn.sendall(head)
            for i in range(len(trickle)):
                if stop.wait(0.2):
                    return
                try:
                    conn.sendall(trickle[i : i + 1])
                except OSError:
                    return
            stop.wait(5)

    def start(head: bytes = b"", trickle: bytes = b"") -> str:
        thread = threading.Thread(target=serve, args=(head, trickle), daemon=True)
        thread.start()
        threads.append(thread)
        return f"http://127.0.0.1:{port}/"

    yield start
    stop.set()
    sock.close()
    for thread in threads:
        thread.join()


def test_bounded_get_times_out_when_server_stalls(slow_http_server):
    url = slow_http_server()
    start = time.monotonic()
    with pytest.raises(galaxy_requests.exceptions.Timeout):
        galaxy_requests.bounded_get(url, timeout=1.0, allowed_schemes=("http",))
    assert time.monotonic() - start < 3


def test_bounded_get_enforces_total_deadline_while_reading(slow_http_server):
    url = slow_http_server(b"HTTP/1.1 200 OK\r\nContent-Length: 100\r\n\r\n", b"x" * 100)
    start = time.monotonic()
    with pytest.raises(galaxy_requests.BoundedFetchError):
        galaxy_requests.bounded_get(url, timeout=1.0, allowed_schemes=("http",))
    assert time.monotonic() - start < 3


@responses.activate
def test_bounded_get_decodes_gzip():
    responses.add(
        responses.GET,
        "https://example.com/a",
        body=gzip.compress("Jörg".encode()),
        content_type="application/x-bibtex",
        headers={"Content-Encoding": "gzip"},
    )
    assert galaxy_requests.bounded_get("https://example.com/a") == "Jörg"


@pytest.fixture
def memory_cache():
    return CacheManager(type="memory").get_cache(uuid.uuid4().hex)


def _counting_fetch(*results):
    calls = []

    def fetch():
        result = results[len(calls)]
        calls.append(result)
        if isinstance(result, Exception):
            raise result
        return result

    return fetch, calls


def _http_error(status):
    response = galaxy_requests.Response()
    response.status_code = status
    return galaxy_requests.exceptions.HTTPError(response=response)


def test_cached_fetch_caches_success(memory_cache):
    fetch, calls = _counting_fetch("value")
    assert galaxy_requests.cached_fetch(memory_cache, "k", fetch, failure_expire=60) == "value"
    assert galaxy_requests.cached_fetch(memory_cache, "k", fetch, failure_expire=60) == "value"
    assert len(calls) == 1


def test_cached_fetch_caches_failure_briefly(memory_cache, monkeypatch):
    fetch, calls = _counting_fetch(_http_error(503), "value")
    for _ in range(2):
        with pytest.raises(galaxy_requests.CachedFetchFailed):
            galaxy_requests.cached_fetch(memory_cache, "k", fetch, failure_expire=60)
    assert len(calls) == 1

    now = time.time()
    monkeypatch.setattr("beaker.container.time.time", lambda: now + 61)
    assert galaxy_requests.cached_fetch(memory_cache, "k", fetch, failure_expire=60) == "value"


def test_cached_fetch_can_keep_not_found(memory_cache, monkeypatch):
    fetch, calls = _counting_fetch(_http_error(404), "value")
    with pytest.raises(galaxy_requests.CachedFetchFailed):
        galaxy_requests.cached_fetch(memory_cache, "k", fetch, failure_expire=60, cache_not_found=True)

    now = time.time()
    monkeypatch.setattr("beaker.container.time.time", lambda: now + 61)
    with pytest.raises(galaxy_requests.CachedFetchFailed):
        galaxy_requests.cached_fetch(memory_cache, "k", fetch, failure_expire=60, cache_not_found=True)
    assert len(calls) == 1


def test_cached_fetch_skips_when_not_allowed(memory_cache):
    fetch, calls = _counting_fetch("value")
    with pytest.raises(galaxy_requests.CachedFetchSkipped):
        galaxy_requests.cached_fetch(memory_cache, "k", fetch, failure_expire=60, may_fetch=lambda: False)
    assert calls == []


def test_cached_fetch_hits_do_not_ask_may_fetch(memory_cache):
    """Cached successes, failures and 404s never spend a fetch allowance."""
    fetch, calls = _counting_fetch("value", _http_error(503), _http_error(404))
    galaxy_requests.cached_fetch(memory_cache, "ok", fetch, failure_expire=60)
    for key in ("failed", "missing"):
        with pytest.raises(galaxy_requests.CachedFetchFailed):
            galaxy_requests.cached_fetch(memory_cache, key, fetch, failure_expire=60, cache_not_found=True)

    asked = []

    def may_fetch():
        asked.append(True)
        return False

    assert galaxy_requests.cached_fetch(memory_cache, "ok", fetch, failure_expire=60, may_fetch=may_fetch) == "value"
    for key in ("failed", "missing"):
        with pytest.raises(galaxy_requests.CachedFetchFailed):
            galaxy_requests.cached_fetch(memory_cache, key, fetch, failure_expire=60, may_fetch=may_fetch)
    assert asked == []
    assert len(calls) == 3
