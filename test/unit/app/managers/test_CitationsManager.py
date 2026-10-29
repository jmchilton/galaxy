import os.path
import tempfile
import time

import pytest
import responses

from galaxy.managers import citations as citations_module
from galaxy.managers.citations import (
    CitationCollection,
    citations_to_bibtex,
    DOI_MAX_RESPONSE_BYTES,
    DoiCache,
    parse_citation,
)
from galaxy.tool_util_models.tool_source import Citation
from galaxy.util.bunch import Bunch
from galaxy.util.unittest_utils import FakeClock

EXAMPLE_DOI = "10.1093/bioinformatics/bts252"
EXAMPLE_BIBTEX = "@article{goecks2010, title={Galaxy}}"


def _cache_config(tmp_database_dir):
    return Bunch(
        citation_cache_type="file",
        citation_cache_data_dir=os.path.join(tmp_database_dir, "data"),
        citation_cache_lock_dir=os.path.join(tmp_database_dir, "locks"),
        citation_cache_url=None,
        citation_cache_table_name=None,
        citation_cache_schema_name=None,
    )


@pytest.fixture
def doi_cache(tmp_path, fake_dns):
    return DoiCache(_cache_config(str(tmp_path)))


def _doi_citation(doi_cache, doi=EXAMPLE_DOI):
    return parse_citation(Citation(type="doi", content=doi), Bunch(doi_cache=doi_cache))


def _bibtex_citation(content=EXAMPLE_BIBTEX):
    return parse_citation(Citation(type="bibtex", content=content), Bunch(doi_cache=None))


@responses.activate
def test_DoiCache(fake_dns):
    with tempfile.TemporaryDirectory() as tmp_database_dir:
        doi_cache = DoiCache(_cache_config(tmp_database_dir))
        dois = (("10.1093/bioinformatics/bts252", "Jörg"), ("10.1101/2021.12.24.474111", "Özkurt"))
        for doi, author in dois:
            responses.add(method="GET", url=f"https://doi.org/{doi}", body=author)
            assert author in doi_cache.get_bibtex(doi)


@responses.activate
def test_doi_cache_requests_bibtex_and_caches(doi_cache):
    responses.add(method="GET", url=f"https://doi.org/{EXAMPLE_DOI}", body=EXAMPLE_BIBTEX)
    assert doi_cache.get_bibtex(EXAMPLE_DOI) == EXAMPLE_BIBTEX
    assert doi_cache.get_bibtex(EXAMPLE_DOI) == EXAMPLE_BIBTEX
    assert len(responses.calls) == 1
    assert responses.calls[0].request.headers["Accept"] == "application/x-bibtex"


@responses.activate
def test_doi_cache_follows_public_redirect(doi_cache):
    responses.add(
        method="GET",
        url=f"https://doi.org/{EXAMPLE_DOI}",
        status=302,
        headers={"Location": "https://api.crossref.org/v1/works/x/transform"},
    )
    responses.add(method="GET", url="https://api.crossref.org/v1/works/x/transform", body=EXAMPLE_BIBTEX)
    assert doi_cache.get_bibtex(EXAMPLE_DOI) == EXAMPLE_BIBTEX


@responses.activate
def test_doi_citation_falls_back_to_stub_on_fetch_error(doi_cache):
    responses.add(method="GET", url=f"https://doi.org/{EXAMPLE_DOI}", status=500)
    bibtex = _doi_citation(doi_cache).to_bibtex()
    assert f"DOI = {{{EXAMPLE_DOI}}}" in bibtex
    assert "Failed to fetch BibTeX for DOI." in bibtex


@responses.activate
def test_citation_collection_dedupes_dois_without_fetching(doi_cache):
    collection = CitationCollection()
    assert collection.add(_doi_citation(doi_cache))
    assert not collection.add(_doi_citation(doi_cache))
    assert collection.add(_doi_citation(doi_cache, "10.1101/2021.12.24.474111"))
    assert len(collection) == 2
    assert len(responses.calls) == 0


def test_citation_collection_dedupes_bibtex():
    collection = CitationCollection()
    assert collection.add(_bibtex_citation())
    assert not collection.add(_bibtex_citation())
    assert len(collection) == 1


@responses.activate
def test_doi_cache_encodes_doi_in_url(doi_cache):
    doi = "10.1000/a?b#c"
    responses.add(method="GET", url="https://doi.org/10.1000/a%3Fb%23c", body=EXAMPLE_BIBTEX)
    assert doi_cache.get_bibtex(doi) == EXAMPLE_BIBTEX


@responses.activate
def test_doi_citation_does_not_follow_redirect_to_local_address(doi_cache):
    responses.add(
        method="GET",
        url=f"https://doi.org/{EXAMPLE_DOI}",
        status=302,
        headers={"Location": "https://internal.example/x"},
    )
    responses.add(method="GET", url="https://internal.example/x", body=EXAMPLE_BIBTEX)
    assert "Failed to fetch BibTeX for DOI." in _doi_citation(doi_cache).to_bibtex()
    assert len(responses.calls) == 1


@responses.activate
def test_doi_citation_caps_response_size(doi_cache):
    responses.add(method="GET", url=f"https://doi.org/{EXAMPLE_DOI}", body="x" * DOI_MAX_RESPONSE_BYTES)
    responses.add(method="GET", url="https://doi.org/10.1000/big", body="x" * (DOI_MAX_RESPONSE_BYTES + 1))
    assert _doi_citation(doi_cache).to_bibtex() == "x" * DOI_MAX_RESPONSE_BYTES
    assert "Failed to fetch BibTeX for DOI." in _doi_citation(doi_cache, "10.1000/big").to_bibtex()


@responses.activate
def test_citation_collection_mixed_types_do_not_fetch(doi_cache):
    responses.add(method="GET", url=f"https://doi.org/{EXAMPLE_DOI}", body=EXAMPLE_BIBTEX)
    collection = CitationCollection()
    assert collection.add(_bibtex_citation())
    assert collection.add(_doi_citation(doi_cache))
    assert len(collection) == 2
    assert len(responses.calls) == 0


@responses.activate
def test_doi_fetch_failure_is_cached_briefly(doi_cache, monkeypatch):
    responses.add(method="GET", url=f"https://doi.org/{EXAMPLE_DOI}", status=500)
    assert "Failed to fetch BibTeX for DOI." in _doi_citation(doi_cache).to_bibtex()
    assert "Failed to fetch BibTeX for DOI." in _doi_citation(doi_cache).to_bibtex()
    assert len(responses.calls) == 1

    now = time.time()
    monkeypatch.setattr("beaker.container.time.time", lambda: now + citations_module.DOI_FAILURE_EXPIRE + 1)
    responses.replace(responses.GET, f"https://doi.org/{EXAMPLE_DOI}", body=EXAMPLE_BIBTEX)
    assert _doi_citation(doi_cache).to_bibtex() == EXAMPLE_BIBTEX
    assert len(responses.calls) == 2


@responses.activate
def test_citations_to_bibtex_limits_fetches(doi_cache):
    dois = [f"10.1000/{i}" for i in range(3)]
    for doi in dois:
        responses.add(method="GET", url=f"https://doi.org/{doi}", body=f"@article{{{doi}}}")
    doi_cache.get_bibtex(dois[0])
    citations = [_doi_citation(doi_cache, doi) for doi in dois]

    first = citations_to_bibtex(citations, max_fetches=1)
    assert [r.content for r in first[:2]] == ["@article{10.1000/0}", "@article{10.1000/1}"]
    assert "Failed to fetch BibTeX for DOI." in first[2].content
    assert len(responses.calls) == 2

    second = citations_to_bibtex(citations, max_fetches=1)
    assert second[2].content == "@article{10.1000/2}"
    assert len(responses.calls) == 3


@responses.activate
def test_doi_fetch_budget_stops_fetching_after_deadline(doi_cache):
    clock = FakeClock()

    def slow_fetch(request):
        clock.advance(citations_module.DOI_FETCH_REQUEST_DEADLINE)
        return (200, {}, "@article{slow}")

    dois = [f"10.1000/{i}" for i in range(3)]
    for doi in dois:
        responses.add_callback(responses.GET, f"https://doi.org/{doi}", callback=slow_fetch)
    citations = [_doi_citation(doi_cache, doi) for doi in dois]

    budget = citations_module.DoiFetchBudget(10, clock=clock)
    results = [citation.to_bibtex(budget) for citation in citations]
    assert results[0] == "@article{slow}"
    assert all("Failed to fetch BibTeX for DOI." in r for r in results[1:])
    assert len(responses.calls) == 1
