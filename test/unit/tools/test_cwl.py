import os

from galaxy.tools.cwl import parser
from galaxy.tools.parser.factory import get_tool_source


TESTS_DIRECTORY = os.path.dirname(__file__)
CWL_TOOLS_DIRECTORY = os.path.join(TESTS_DIRECTORY, "cwl_tools")


def test_proxy():
    print parser.tool_proxy(_cwl_tool_path("draft1/cat1-tool.json"))
    print parser.tool_proxy(_cwl_tool_path("draft2/cat3-tool.cwl"))
    assert False


def test_load_proxy():
    cat3 = _cwl_tool_path("draft2/cat3-tool.cwl")
    tool_source = get_tool_source(cat3)
    input_pages = tool_source.parse_input_pages()
    assert input_pages.inputs_defined
    page_sources = input_pages.page_sources
    assert len(page_sources) == 1
    page_source = page_sources[0]
    input_sources = page_source.parse_input_sources()
    assert len(input_sources) == 1

    outputs, output_collections = tool_source.parse_outputs(None)
    assert len(outputs) == 1


def _cwl_tool_path(path):
    return os.path.join(CWL_TOOLS_DIRECTORY, path)
