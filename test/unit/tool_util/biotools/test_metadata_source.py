import os

import responses

from galaxy.tool_util.biotools.source import (
    ApiBiotoolsMetadataSource,
    BiotoolsMetadataSourceConfig,
    get_biotools_metadata_source,
    GitContentBiotoolsMetadataSource,
)
from galaxy.util.unittest_utils import skip_if_site_down
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


class _DictCache:
    def __init__(self):
        self.backend = {}

    def get(self, key, createfunc):
        if key not in self.backend:
            self.backend[key] = createfunc()
        return self.backend[key]


@responses.activate
def test_api_content_offline():
    with open(os.path.join(content_dir, "data", "bwa", "bwa.biotools.json")) as f:
        responses.add(method="GET", url="https://bio.tools/api/tool/bwa?format=json", body=f.read())
    responses.add(method="GET", url="https://bio.tools/api/tool/johnscoolbowtie?format=json", status=404)
    metadata_source = ApiBiotoolsMetadataSource(cache=_DictCache())
    bwa_entry = metadata_source.get_biotools_metadata("bwa")
    assert bwa_entry is not None
    assert len(bwa_entry.function) == 6
    assert metadata_source.get_biotools_metadata("johnscoolbowtie") is None
    assert metadata_source.get_biotools_metadata("johnscoolbowtie") is None
    assert len(responses.calls) == 2


@responses.activate
def test_api_content_encodes_reference():
    with open(os.path.join(content_dir, "data", "bwa", "bwa.biotools.json")) as f:
        responses.add(method="GET", url="https://bio.tools/api/tool/a%3Fb?format=json", body=f.read())
    assert ApiBiotoolsMetadataSource(cache=_DictCache()).get_biotools_metadata("a?b") is not None


@responses.activate
def test_api_content_validates_redirects():
    responses.add(
        method="GET",
        url="https://bio.tools/api/tool/bwa?format=json",
        status=302,
        headers={"Location": "https://internal.example/bwa"},
    )
    validated = []

    def validate_url(url):
        validated.append(url)
        if "internal.example" in url:
            raise ValueError(url)

    metadata_source = ApiBiotoolsMetadataSource(cache=_DictCache(), validate_url=validate_url)
    assert metadata_source.get_biotools_metadata("bwa") is None
    assert validated == ["https://bio.tools/api/tool/bwa?format=json", "https://internal.example/bwa"]
    assert len(responses.calls) == 1
