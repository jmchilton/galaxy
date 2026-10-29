import os

import responses

from galaxy.managers.citations import DoiCache
from galaxy.tools.biotools import get_galaxy_biotools_metadata_source
from galaxy.util.bunch import Bunch

BWA_JSON = os.path.join(
    os.path.dirname(__file__), "..", "..", "tool_util", "biotools", "mock_content", "data", "bwa", "bwa.biotools.json"
)
BWA_API_URL = "https://bio.tools/api/tool/bwa?format=json"


def _biotools_config(cache_dir):
    return Bunch(
        biotools_content_directory=None,
        biotools_use_api=True,
        biotools_service_cache_type="file",
        biotools_service_cache_data_dir=os.path.join(cache_dir, "data"),
        biotools_service_cache_lock_dir=os.path.join(cache_dir, "locks"),
        biotools_service_cache_url=None,
        biotools_service_cache_table_name="beaker_cache",
        biotools_service_cache_schema_name=None,
        fetch_url_allowlist_ips=[],
    )


@responses.activate
def test_biotools_lookups_do_not_share_doi_cache_entries(tmp_path, fake_dns):
    doi_cache = DoiCache(
        Bunch(
            citation_cache_type="file",
            citation_cache_data_dir=str(tmp_path / "data"),
            citation_cache_lock_dir=str(tmp_path / "locks"),
            citation_cache_url=None,
            citation_cache_table_name="beaker_cache",
            citation_cache_schema_name=None,
        )
    )
    responses.add(responses.GET, "https://doi.org/bwa", body="@misc{bwa}")
    assert doi_cache.get_bibtex("bwa") == "@misc{bwa}"
    with open(BWA_JSON) as f:
        responses.add(responses.GET, BWA_API_URL, body=f.read())
    entry = get_galaxy_biotools_metadata_source(_biotools_config(str(tmp_path))).get_biotools_metadata("bwa")
    assert entry is not None
    assert len(entry.function) == 6


@responses.activate
def test_biotools_lookup_does_not_follow_redirect_to_local_address(tmp_path, fake_dns):
    responses.add(responses.GET, BWA_API_URL, status=302, headers={"Location": "https://internal.example/bwa"})
    with open(BWA_JSON) as f:
        responses.add(responses.GET, "https://internal.example/bwa", body=f.read())
    source = get_galaxy_biotools_metadata_source(_biotools_config(str(tmp_path)))
    assert source.get_biotools_metadata("bwa") is None
    assert len(responses.calls) == 1
