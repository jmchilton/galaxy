import functools
import json
import os
import time
from typing import (
    Any,
    Callable,
    Dict,
    List,
    Optional,
    Tuple,
)
from urllib.parse import quote

from galaxy.util.requests import (
    bounded_get,
    cached_fetch,
    CachedFetchFailed,
    FetchCache,
    UrlValidator,
)
from .interface import BiotoolsEntry

BIOTOOLS_FAILURE_EXPIRE = 3600


class BiotoolsMetadataSource:
    def get_biotools_metadata(self, biotools_reference: str) -> Optional[BiotoolsEntry]:
        """Return a BiotoolsEntry if available."""


class GitContentBiotoolsMetadataSource(BiotoolsMetadataSource):
    """Parse entries from a repository clone of https://github.com/bio-tools/content."""

    def __init__(self, content_directory):
        self._content_directory = content_directory

    def get_biotools_metadata(self, biotools_reference: str) -> Optional[BiotoolsEntry]:
        """Return a BiotoolsEntry if available."""
        path = os.path.join(self._content_directory, "data", biotools_reference, f"{biotools_reference}.biotools.json")
        if not os.path.exists(path):
            return None
        with open(path) as f:
            content_json = json.load(f)
            return BiotoolsEntry.from_json(content_json)


class InMemoryCache:
    """A ``FetchCache`` kept in a dict, with optional per-entry expiry."""

    def __init__(self, clock: Callable[[], float] = time.monotonic) -> None:
        self._backend: Dict[str, Tuple[Any, Optional[float]]] = {}
        self._clock = clock

    def get(self, key: str) -> Any:
        value, expires = self._backend[key]
        if expires is not None and self._clock() >= expires:
            del self._backend[key]
            raise KeyError(key)
        return value

    def put(self, key: str, value: Any, expiretime: Optional[float] = None) -> None:
        self._backend[key] = (value, None if expiretime is None else self._clock() + expiretime)


# Shared so short-lived sources, like one per linted xref, reuse lookups.
DEFAULT_CACHE = InMemoryCache()


class ApiBiotoolsMetadataSource(BiotoolsMetadataSource):
    """Parse entries from bio.tools API."""

    def __init__(self, cache: Optional[FetchCache] = None, validate_url: Optional[UrlValidator] = None):
        self._cache = cache or DEFAULT_CACHE
        self._validate_url = validate_url

    def _raw_get_metadata(self, biotools_reference: str) -> str:
        api_url = f"https://bio.tools/api/tool/{quote(biotools_reference, safe='')}?format=json"
        return bounded_get(api_url, validate_url=self._validate_url)

    def get_biotools_metadata(self, biotools_reference: str) -> Optional[BiotoolsEntry]:
        try:
            content = cached_fetch(
                self._cache,
                biotools_reference,
                functools.partial(self._raw_get_metadata, biotools_reference),
                failure_expire=BIOTOOLS_FAILURE_EXPIRE,
                cache_not_found=True,
            )
        except CachedFetchFailed:
            return None
        return BiotoolsEntry.from_json(json.loads(content))


class CascadingBiotoolsMetadataSource(BiotoolsMetadataSource):
    def __init__(
        self,
        use_api=False,
        cache: Optional[FetchCache] = None,
        content_directory: Optional[str] = None,
        validate_url: Optional[UrlValidator] = None,
    ):
        sources: List[BiotoolsMetadataSource] = []
        if content_directory:
            git_content_source = GitContentBiotoolsMetadataSource(content_directory)
            sources.append(git_content_source)
        if use_api:
            api_metadata_source = ApiBiotoolsMetadataSource(cache=cache, validate_url=validate_url)
            sources.append(api_metadata_source)
        self._sources = sources

    def get_biotools_metadata(self, biotools_reference: str) -> Optional[BiotoolsEntry]:
        for source in self._sources:
            entry = source.get_biotools_metadata(biotools_reference)
            if entry is not None:
                return entry
        return None


class BiotoolsMetadataSourceConfig:
    use_api: bool = False
    content_directory: Optional[str] = None
    cache: Optional[FetchCache] = None
    validate_url: Optional[UrlValidator] = None


def get_biotools_metadata_source(metadata_source_config: BiotoolsMetadataSourceConfig) -> BiotoolsMetadataSource:
    return CascadingBiotoolsMetadataSource(
        use_api=metadata_source_config.use_api,
        content_directory=metadata_source_config.content_directory,
        cache=metadata_source_config.cache,
        validate_url=metadata_source_config.validate_url,
    )
