from galaxy.managers.citations import (
    BibtexCitation,
    CitationCollection,
    CitationsManager,
    parse_citation,
)
from galaxy.model.unittest_utils import GalaxyDataTestApp
from galaxy.tool_util.parser import get_tool_source
from galaxy.tool_util.parser.xml import parse_citation_elem
from galaxy.tools import create_tool_from_source
from galaxy.util import parse_xml_string

EXAMPLE_BIBTEX_CITATION = """<citation type="bibtex">@article{goecks2010galaxy,
    title={Galaxy: a comprehensive approach for supporting accessible, reproducible, and transparent computational research in the life sciences},
    author={Goecks, Jeremy and Nekrutenko, Anton and Taylor, James and The Galaxy Team},
    journal={Genome Biol},
    volume={11},
    number={8},
    pages={R86},
    year={2010}
}</citation>"""


def test_parse_citation():
    xml_text = EXAMPLE_BIBTEX_CITATION
    citation_elem = parse_xml_string(xml_text)
    citation_model = parse_citation_elem(citation_elem)
    assert citation_model
    citation = parse_citation(citation_model, None)
    assert citation
    bibtex = citation.to_bibtex()
    assert "title={Galaxy" in bibtex


def test_citation_collection():
    citation_collection = CitationCollection()
    assert len(citation_collection) == 0
    cite1 = QuickBibtexCitation("@article{'test1'}")
    cite1dup = QuickBibtexCitation("@article{'test1'}")
    cite2 = QuickBibtexCitation("@article{'test2'}")
    assert citation_collection.add(cite1)
    assert not citation_collection.add(cite1dup)
    assert citation_collection.add(cite2)
    assert len(citation_collection) == 2


class QuickBibtexCitation(BibtexCitation):
    def __init__(self, raw_bibtex):
        self.raw_bibtex = raw_bibtex


class CitationsToolApp(GalaxyDataTestApp):
    name = "galaxy"
    biotools_metadata_source = None
    job_search = None
    is_webapp = True

    def __init__(self, tmp_path):
        super().__init__()
        self.config.citation_cache_type = "file"
        self.config.citation_cache_data_dir = str(tmp_path / "data")
        self.config.citation_cache_lock_dir = str(tmp_path / "locks")
        self.config.citation_cache_url = None
        self.config.citation_cache_table_name = None
        self.config.citation_cache_schema_name = None
        self.citations_manager = CitationsManager(self)


def _tool_with_citations(tmp_path, citations_xml):
    raw = f'<tool id="cite" name="cite" version="1" profile="26.1"><citations>{citations_xml}</citations></tool>'
    tool_source = get_tool_source(tool_source_class="XmlToolSource", raw_tool_source=raw)
    return create_tool_from_source(CitationsToolApp(tmp_path), tool_source=tool_source)


def test_tool_loads_citations_in_order(tmp_path):
    dois = [f"10.1000/{i}" for i in range(3)]
    tool = _tool_with_citations(tmp_path, "".join(f'<citation type="doi">{doi}</citation>' for doi in dois))
    assert [citation.doi() for citation in tool.citations] == dois
