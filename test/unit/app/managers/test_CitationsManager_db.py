import time

import pytest
import responses
from requests.exceptions import HTTPError

import galaxy.config
from galaxy.managers.citations import (
    DOI_FAILURE_EXPIRE,
    DoiCache,
    DoiFetchFailed,
)
from galaxy.model.unittest_utils.beaker_testing_utils import is_cache_empty
from galaxy.model.unittest_utils.migration_scripts_testing_utils import tmp_directory  # noqa: F401
from galaxy.model.unittest_utils.model_testing_utils import (  # noqa: F401  (url_factory is a fixture we have to import explicitly)
    create_and_drop_database,
    url_factory,
)


class MockDoiCache(DoiCache):
    def __init__(self, config, db_url):
        self._db_url = db_url
        super().__init__(config)
        self._cache.clear()

    def _cache_options(self, config):
        return {
            "cache.type": "ext:database",
            "cache.data_dir": config.citation_cache_data_dir,
            "cache.url": self._db_url,
            "cache.table_name": config.citation_cache_table_name,
            "cache.schema_name": config.citation_cache_schema_name,
        }


@responses.activate
def test_DoiCache(url_factory, fake_dns):  # noqa: F811
    db_url = url_factory()
    with create_and_drop_database(db_url):
        doi_cache = MockDoiCache(galaxy.config.GalaxyAppConfiguration(override_tempdir=False), db_url)
        assert is_cache_empty(db_url, "doi")
        dois = (("10.1093/bioinformatics/bts252", "Jörg"), ("10.1101/2021.12.24.474111", "Özkurt"))
        for doi, author in dois:
            responses.add(method="GET", url=f"https://doi.org/{doi}", body=author)
            assert author in doi_cache.get_bibtex(doi)
        assert not is_cache_empty(db_url, "doi")
        doi_cache._cache.clear()
        assert is_cache_empty(db_url, "doi")


@responses.activate
def test_DoiCache_failure_expires(url_factory, fake_dns, monkeypatch):  # noqa: F811
    db_url = url_factory()
    doi = "10.1093/bioinformatics/bts252"
    with create_and_drop_database(db_url):
        doi_cache = MockDoiCache(galaxy.config.GalaxyAppConfiguration(override_tempdir=False), db_url)
        responses.add(method="GET", url=f"https://doi.org/{doi}", status=500)
        with pytest.raises(HTTPError):
            doi_cache.get_bibtex(doi)
        with pytest.raises(DoiFetchFailed):
            doi_cache.get_bibtex(doi)
        assert len(responses.calls) == 1

        now = time.time()
        monkeypatch.setattr("beaker.container.time.time", lambda: now + DOI_FAILURE_EXPIRE + 1)
        responses.replace(responses.GET, f"https://doi.org/{doi}", body="Jörg")
        assert doi_cache.get_bibtex(doi) == "Jörg"
