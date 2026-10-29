import time
from typing import (
    Any,
    Callable,
    Dict,
    Iterator,
    Optional,
    Sequence,
    Union,
)
from urllib.parse import (
    urljoin,
    urlparse,
)

import requests
from requests import (  # noqa: F401
    codes as codes,
    exceptions as exceptions,
    Response as Response,
)
from requests.adapters import HTTPAdapter
from requests.packages.urllib3.util.retry import Retry
from typing_extensions import (
    ParamSpec,
    Protocol,
)

from .user_agent import get_default_headers

DEFAULT_RETRIES = 3
DEFAULT_BACKOFF_FACTOR = 0.1
DEFAULT_BOUNDED_TIMEOUT = 15.0
DEFAULT_BOUNDED_MAX_BYTES = 1024 * 1024
DEFAULT_BOUNDED_MAX_REDIRECTS = 3
BOUNDED_READ_CHUNK_SIZE = 16 * 1024

CACHED_FETCH_FAILED = "__galaxy_cached_fetch_failed__"

UrlValidator = Callable[[str], object]


class Session(requests.Session):
    def __init__(self) -> None:
        super().__init__()
        self.headers.update(get_default_headers())


class RetrySession(Session):
    def __init__(
        self, total: Union[bool, int, None] = DEFAULT_RETRIES, backoff_factor: float = DEFAULT_BACKOFF_FACTOR, **kwargs
    ) -> None:
        super().__init__()
        retry = Retry(total=total, backoff_factor=backoff_factor, **kwargs)
        adapter = HTTPAdapter(max_retries=retry)
        self.mount("https://", adapter)
        self.mount("http://", adapter)


Param = ParamSpec("Param")


def _request_decorator(f: Callable[Param, Response]) -> Callable[Param, Response]:
    def wrapper(*args: Param.args, **kwargs: Param.kwargs) -> Response:
        with Session() as s:
            return getattr(s, f.__name__)(*args, **kwargs)

    return wrapper


delete = _request_decorator(requests.delete)
get = _request_decorator(requests.get)
head = _request_decorator(requests.head)
patch = _request_decorator(requests.patch)
post = _request_decorator(requests.post)
options = _request_decorator(requests.options)
put = _request_decorator(requests.put)
session = Session


class BoundedFetchError(Exception):
    pass


def bounded_get(
    url: str,
    *,
    headers: Optional[Dict[str, str]] = None,
    timeout: float = DEFAULT_BOUNDED_TIMEOUT,
    max_bytes: int = DEFAULT_BOUNDED_MAX_BYTES,
    max_redirects: int = DEFAULT_BOUNDED_MAX_REDIRECTS,
    allowed_schemes: Sequence[str] = ("https",),
    validate_url: Optional[UrlValidator] = None,
) -> str:
    """GET ``url`` as text within a time, response size and redirect budget.

    Each URL (including every redirect target) is normalized and checked with ``validate_url`` before it is
    requested. The deadline is checked between body reads; connecting and reading headers are bounded only
    per socket read (by the time left) and by ``http.client``'s header limits, and DNS resolution isn't covered.
    """
    deadline = time.monotonic() + timeout
    with Session() as session:
        for _ in range(max_redirects + 1):
            parsed_url = urlparse(url)
            url = parsed_url.geturl()
            if parsed_url.scheme not in allowed_schemes:
                raise BoundedFetchError(f"Refusing to fetch '{url}', scheme not in {list(allowed_schemes)}")
            if validate_url is not None:
                validate_url(url)
            with session.get(
                url, headers=headers, timeout=_remaining(deadline), stream=True, allow_redirects=False
            ) as response:
                if response.is_redirect:
                    url = urljoin(url, response.headers["location"])
                    continue
                response.raise_for_status()
                content = bytearray()
                for chunk in _iter_reads(response):
                    content.extend(chunk)
                    if len(content) > max_bytes:
                        raise BoundedFetchError(f"Response from '{url}' exceeds {max_bytes} bytes")
                    _remaining(deadline)
                return content.decode(response.encoding or "utf-8", errors="replace")
    raise BoundedFetchError(f"Too many redirects fetching '{url}'")


def _iter_reads(response: Response) -> Iterator[bytes]:
    # urllib3 2's read1 returns whatever one socket read yields; iter_content waits to fill each chunk.
    read1 = getattr(response.raw, "read1", None)
    if read1 is None:
        yield from response.iter_content(chunk_size=BOUNDED_READ_CHUNK_SIZE)
        return
    while chunk := read1(BOUNDED_READ_CHUNK_SIZE, decode_content=True):
        yield chunk


def _remaining(deadline: float) -> float:
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise BoundedFetchError("Timed out")
    return remaining


class FetchCache(Protocol):
    """A beaker ``Cache``-like store; ``get`` raises ``KeyError`` for missing or expired keys."""

    def get(self, key: str) -> Any: ...

    def put(self, key: str, value: Any, expiretime: Optional[float] = None) -> None: ...


class CachedFetchFailed(Exception):
    pass


class CachedFetchSkipped(Exception):
    pass


def cached_fetch(
    cache: FetchCache,
    key: str,
    fetch: Callable[[], str],
    *,
    failure_expire: float,
    cache_not_found: bool = False,
    may_fetch: Optional[Callable[[], bool]] = None,
) -> str:
    """Return ``fetch()``'s result for ``key`` from ``cache``, fetching on a miss.

    Failures are cached for ``failure_expire`` seconds; with ``cache_not_found``, a 404 is kept like a success.
    """
    try:
        value = cache.get(key)
    except KeyError:
        if may_fetch is not None and not may_fetch():
            raise CachedFetchSkipped(key)
        try:
            value = fetch()
        except Exception as e:
            if cache_not_found and _is_not_found(e):
                cache.put(key, CACHED_FETCH_FAILED)
            else:
                cache.put(key, CACHED_FETCH_FAILED, expiretime=failure_expire)
            raise CachedFetchFailed(f"{key}: {e!r}") from e
        cache.put(key, value)
    if value == CACHED_FETCH_FAILED:
        raise CachedFetchFailed(f"{key}: failed recently")
    return value


def _is_not_found(e: Exception) -> bool:
    return isinstance(e, exceptions.HTTPError) and e.response is not None and e.response.status_code == 404
