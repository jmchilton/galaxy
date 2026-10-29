import os.path
import tempfile

import pytest
import responses

from galaxy.managers.citations import (
    CitationCollection,
    DoiCache,
    parse_citation,
)
from galaxy.tool_util_models.tool_source import Citation
from galaxy.util.bunch import Bunch

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
def doi_cache(tmp_path):
    return DoiCache(_cache_config(str(tmp_path)))


def _doi_citation(doi_cache, doi=EXAMPLE_DOI):
    return parse_citation(Citation(type="doi", content=doi), Bunch(doi_cache=doi_cache))


def _bibtex_citation(content=EXAMPLE_BIBTEX):
    return parse_citation(Citation(type="bibtex", content=content), Bunch(doi_cache=None))


@responses.activate
def test_DoiCache():
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
