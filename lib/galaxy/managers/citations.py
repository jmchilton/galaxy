import functools
import logging
import time
from collections.abc import Iterable
from typing import (
    Optional,
    Union,
)
from urllib.parse import quote

from beaker.cache import CacheManager
from beaker.util import parse_cache_config_options

from galaxy.files.uris import validate_non_local
from galaxy.schema.citations import (
    BibtexCitationResponse,
    CitationErrorResponse,
)
from galaxy.structured_app import BasicSharedApp
from galaxy.tool_util_models.tool_source import Citation
from galaxy.util.requests import bounded_get

log = logging.getLogger(__name__)

CitationT = Union["BibtexCitation", "DoiCitation"]
OptionalCitationT = Optional[CitationT]

DOI_FETCH_TIMEOUT = 10.0
DOI_MAX_RESPONSE_BYTES = 64 * 1024
DOI_FAILURE_EXPIRE = 600
DOI_FETCH_FAILED = "__galaxy_doi_fetch_failed__"
DOI_MAX_FETCHES_PER_REQUEST = 10
DOI_FETCH_REQUEST_DEADLINE = 30.0
MAX_CITATIONS_PER_TOOL = 50
MAX_BIBTEX_CITATION_LENGTH = 32 * 1024


class DoiFetchFailed(Exception):
    pass


class DoiFetchSkipped(Exception):
    pass


class DoiFetchBudget:
    """Number of uncached DOI lookups one request may make, and how long it may keep starting them."""

    def __init__(self, max_fetches: int, deadline: float = DOI_FETCH_REQUEST_DEADLINE) -> None:
        self.remaining = max_fetches
        self.deadline = time.monotonic() + deadline

    def take(self) -> bool:
        # A fetch started before the deadline still runs to its own timeout.
        if self.remaining <= 0 or time.monotonic() >= self.deadline:
            return False
        self.remaining -= 1
        return True


class CitationsManager:
    def __init__(self, app: BasicSharedApp) -> None:
        self.app = app
        self.doi_cache = DoiCache(app.config)
        # The Tool Shed's config has no citation fetch options.
        self.max_fetches_per_request = getattr(
            app.config, "citation_max_fetches_per_request", DOI_MAX_FETCHES_PER_REQUEST
        )

    def citations_for_tool(self, tool):
        return tool.citations

    def citations_for_tool_ids(self, tool_ids):
        citation_collection = CitationCollection()
        errors: list[CitationErrorResponse] = []
        for tool_id in tool_ids:
            tool = self._get_tool(tool_id)
            if not tool:
                log.warning("Tool '%s' not found, citations may be missing.", tool_id)
                errors.append(
                    CitationErrorResponse(
                        error=f"Tool '{tool_id}' not found. Citations for this tool may be missing.",
                        tool_id=tool_id,
                    )
                )
                continue
            for citation in self.citations_for_tool(tool):
                citation_collection.add(citation)
        return citation_collection.citations, errors

    def parse_citation(self, citation_model: Citation) -> OptionalCitationT:
        return parse_citation(citation_model, self)

    def parse_citations(self, citation_models: list[Citation], tool_id: Optional[str] = None) -> list[CitationT]:
        """Parse a tool's citations, dropping oversized BibTeX and any beyond MAX_CITATIONS_PER_TOOL."""
        citations: list[CitationT] = []
        for citation_model in citation_models:
            if citation_model.type == "bibtex" and len(citation_model.content) > MAX_BIBTEX_CITATION_LENGTH:
                log.warning(
                    "Tool '%s' has a BibTeX citation over %d characters, skipping it.",
                    tool_id,
                    MAX_BIBTEX_CITATION_LENGTH,
                )
                continue
            citation = self.parse_citation(citation_model)
            if citation:
                citations.append(citation)
        if len(citations) > MAX_CITATIONS_PER_TOOL:
            log.warning(
                "Tool '%s' declares %d citations, keeping the first %d.",
                tool_id,
                len(citations),
                MAX_CITATIONS_PER_TOOL,
            )
            citations = citations[:MAX_CITATIONS_PER_TOOL]
        return citations

    def citations_to_bibtex(self, citations: Iterable[CitationT]) -> list[BibtexCitationResponse]:
        return citations_to_bibtex(citations, self.max_fetches_per_request)

    def _get_tool(self, tool_id):
        tool = self.app.toolbox.get_tool(tool_id)
        return tool


class DoiCache:
    def __init__(self, config):
        # The Tool Shed's config has no fetch_url_allowlist or citation fetch options.
        self._cache = CacheManager(**parse_cache_config_options(self._cache_options(config))).get_cache(
            "doi", expire=getattr(config, "citation_cache_expire", 0) or None
        )
        self._fetch_timeout = getattr(config, "citation_fetch_timeout", DOI_FETCH_TIMEOUT)
        self._validate_url = functools.partial(
            validate_non_local, ip_allowlist=getattr(config, "fetch_url_allowlist_ips", None) or []
        )

    def _cache_options(self, config) -> dict:
        return {
            "cache.type": config.citation_cache_type,
            "cache.data_dir": config.citation_cache_data_dir,
            "cache.lock_dir": config.citation_cache_lock_dir,
            "cache.url": config.citation_cache_url,
            "cache.table_name": config.citation_cache_table_name,
            "cache.schema_name": config.citation_cache_schema_name,
        }

    def _raw_get_bibtex(self, doi):
        # bounded_get decodes with the declared charset, else utf-8 (guessing is sometimes wrong).
        return bounded_get(
            f"https://doi.org/{quote(doi, safe='/')}",
            headers={"Accept": "application/x-bibtex"},
            timeout=self._fetch_timeout,
            max_bytes=DOI_MAX_RESPONSE_BYTES,
            validate_url=self._validate_url,
        )

    def get_bibtex(self, doi: str, budget: Optional[DoiFetchBudget] = None) -> str:
        try:
            bibtex = self._cache.get(key=doi)
        except KeyError:
            if budget is not None and not budget.take():
                raise DoiFetchSkipped(doi)
            try:
                bibtex = self._raw_get_bibtex(doi)
            except Exception:
                self._cache.put(doi, DOI_FETCH_FAILED, expiretime=DOI_FAILURE_EXPIRE)
                raise
            self._cache.put(doi, bibtex)
        if bibtex == DOI_FETCH_FAILED:
            raise DoiFetchFailed(doi)
        return bibtex


def citations_to_bibtex(
    citations: Iterable[CitationT], max_fetches: int = DOI_MAX_FETCHES_PER_REQUEST
) -> list[BibtexCitationResponse]:
    budget = DoiFetchBudget(max_fetches)
    return [BibtexCitationResponse(content=citation.to_bibtex(budget)) for citation in citations]


def parse_citation(citation_model: Citation, citation_manager) -> OptionalCitationT:
    """
    Parse an abstract citation entry from the specified XML element.
    """
    citation_type = citation_model.type
    citation_class = CITATION_CLASSES.get(citation_type, None)
    if not citation_class:
        log.warning(f"Unknown or unspecified citation type: {citation_type}")
        return None
    try:
        citation = citation_class(citation_model, citation_manager)
    except Exception as e:
        raise Exception(f"Invalid citation of type '{citation_type}' with content '{citation_model.content}': {e}")
    return citation


class CitationCollection:
    def __init__(self):
        self.citations = []

    def __iter__(self):
        return self.citations.__iter__()

    def __len__(self):
        return len(self.citations)

    def add(self, new_citation):
        for citation in self.citations:
            if citation.equals(new_citation):
                # TODO: We have two equivalent citations, pick the more
                # informative/complete/correct.
                return False

        self.citations.append(new_citation)
        return True


class BaseCitation:
    def to_dict(self, citation_format):
        if citation_format == "bibtex":
            return BibtexCitationResponse(content=self.to_bibtex())
        else:
            raise Exception(f"Unknown citation format {citation_format}")

    def equals(self, other_citation):
        if self.has_doi() and other_citation.has_doi():
            return self.doi() == other_citation.doi()
        elif self.has_doi() or other_citation.has_doi():
            # Resolving the DOI just to compare isn't worth a fetch.
            return False
        else:
            # TODO: Do a better job figuring out if this is the same citation.
            return self.to_bibtex() == other_citation.to_bibtex()

    def has_doi(self):
        return False


class BibtexCitation(BaseCitation):
    def __init__(self, citation_model: Citation, citation_manager: CitationsManager):
        self.raw_bibtex = citation_model.content

    def to_bibtex(self, budget: Optional[DoiFetchBudget] = None) -> str:
        return self.raw_bibtex


BIBTEX_UNSET = object()


class DoiCitation(BaseCitation):

    def __init__(self, citation_model: Citation, citation_manager: CitationsManager):
        self.__doi = citation_model.content
        self.doi_cache = citation_manager.doi_cache
        self.raw_bibtex = BIBTEX_UNSET

    def has_doi(self):
        return True

    def doi(self):
        return self.__doi

    def to_bibtex(self, budget: Optional[DoiFetchBudget] = None) -> str:
        if self.raw_bibtex is BIBTEX_UNSET:
            try:
                self.raw_bibtex = self.doi_cache.get_bibtex(self.__doi, budget)
            except Exception as e:
                log.debug("No bibtex for DOI %s: %r", self.__doi, e)

        if self.raw_bibtex is BIBTEX_UNSET:
            return f"""@MISC{{{self.__doi},
                DOI = {{{self.__doi}}},
                note = {{Failed to fetch BibTeX for DOI.}}
            }}"""
        else:
            return str(self.raw_bibtex)


CITATION_CLASSES: dict[str, type[CitationT]] = dict(
    bibtex=BibtexCitation,
    doi=DoiCitation,
)
