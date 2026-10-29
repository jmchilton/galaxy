import os

import responses

from galaxy.tool_util.biotools import source as source_module
from galaxy.tool_util.biotools.source import (
    ApiBiotoolsMetadataSource,
    BiotoolsMetadataSourceConfig,
    get_biotools_metadata_source,
    GitContentBiotoolsMetadataSource,
    InMemoryCache,
)
from galaxy.util.unittest_utils import (
    FakeClock,
    skip_if_site_down,
)
from ._util import content_dir


def test_git_content():
    metadata_source = GitContentBiotoolsMetadataSource(content_dir)
    bwa_entry = metadata_source.get_biotools_metadata("bwa")
    assert bwa_entry is not None
    assert len(bwa_entry.function) == 6

    missing_entry = metadata_source.get_biotools_metadata("johnscoolbowtie")
    assert missing_entry is None


@skip_if_site_down("https://bio.tools/")
def test_api_content():
    metadata_source = ApiBiotoolsMetadataSource()
    bwa_entry = metadata_source.get_biotools_metadata("bwa")
    assert bwa_entry is not None
    assert len(bwa_entry.function) >= 6

    missing_entry = metadata_source.get_biotools_metadata("johnscoolbowtie")
    assert missing_entry is None


@skip_if_site_down("https://bio.tools/")
def test_cascade_content():
    config = BiotoolsMetadataSourceConfig()
    config.content_directory = content_dir
    metadata_source = get_biotools_metadata_source(config)
    bwa_entry = metadata_source.get_biotools_metadata("bwa")
    assert bwa_entry is not None
    assert len(bwa_entry.function) == 6

    # by default API isn't used so bowtie2 empty...
    bowtie2 = metadata_source.get_biotools_metadata("bowtie2")
    assert bowtie2 is None

    # but can be enabled with API
    config = BiotoolsMetadataSourceConfig()
    config.content_directory = content_dir
    config.use_api = True
    metadata_source = get_biotools_metadata_source(config)
    bowtie2 = metadata_source.get_biotools_metadata("bowtie2")
    assert bowtie2 is not None
    assert len(bowtie2.topic) == 3


@responses.activate
def test_api_content_offline():
    with open(os.path.join(content_dir, "data", "bwa", "bwa.biotools.json")) as f:
        responses.add(method="GET", url="https://bio.tools/api/tool/bwa?format=json", body=f.read())
    responses.add(method="GET", url="https://bio.tools/api/tool/johnscoolbowtie?format=json", status=404)
    clock = FakeClock()
    metadata_source = ApiBiotoolsMetadataSource(cache=InMemoryCache(clock=clock))
    bwa_entry = metadata_source.get_biotools_metadata("bwa")
    assert bwa_entry is not None
    assert len(bwa_entry.function) == 6
    assert metadata_source.get_biotools_metadata("johnscoolbowtie") is None
    assert metadata_source.get_biotools_metadata("johnscoolbowtie") is None
    assert len(responses.calls) == 2

    clock.advance(source_module.BIOTOOLS_FAILURE_EXPIRE + 1)
    assert metadata_source.get_biotools_metadata("johnscoolbowtie") is None
    assert len(responses.calls) == 2


@responses.activate
def test_api_content_encodes_reference():
    with open(os.path.join(content_dir, "data", "bwa", "bwa.biotools.json")) as f:
        responses.add(method="GET", url="https://bio.tools/api/tool/a%3Fb?format=json", body=f.read())
    assert ApiBiotoolsMetadataSource(cache=InMemoryCache()).get_biotools_metadata("a?b") is not None


@responses.activate
def test_api_content_retries_failed_lookup_after_expiry():
    responses.add(method="GET", url="https://bio.tools/api/tool/bwa?format=json", status=503)
    clock = FakeClock()
    metadata_source = ApiBiotoolsMetadataSource(cache=InMemoryCache(clock=clock))
    assert metadata_source.get_biotools_metadata("bwa") is None
    assert metadata_source.get_biotools_metadata("bwa") is None
    assert len(responses.calls) == 1

    with open(os.path.join(content_dir, "data", "bwa", "bwa.biotools.json")) as f:
        responses.replace(responses.GET, "https://bio.tools/api/tool/bwa?format=json", body=f.read())
    clock.advance(source_module.BIOTOOLS_FAILURE_EXPIRE + 1)
    assert metadata_source.get_biotools_metadata("bwa") is not None
    assert len(responses.calls) == 2


@responses.activate
def test_api_sources_with_separate_caches_do_not_share_lookups():
    with open(os.path.join(content_dir, "data", "bwa", "bwa.biotools.json")) as f:
        responses.add(method="GET", url="https://bio.tools/api/tool/bwa?format=json", body=f.read())
    for _ in range(2):
        assert ApiBiotoolsMetadataSource(cache=InMemoryCache()).get_biotools_metadata("bwa") is not None
    assert len(responses.calls) == 2
