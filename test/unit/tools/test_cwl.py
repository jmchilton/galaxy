import os

from galaxy.tools.cwl import tool_proxy
from galaxy.tools.parser.factory import get_tool_source


TESTS_DIRECTORY = os.path.dirname(__file__)
CWL_TOOLS_DIRECTORY = os.path.join(TESTS_DIRECTORY, "cwl_tools")


def test_proxy():
    print tool_proxy(_cwl_tool_path("draft1/cat1-tool.json"))
    print tool_proxy(_cwl_tool_path("draft2/cat3-tool.cwl"))
    print tool_proxy(_cwl_tool_path("draft2/env-tool1.cwl"))


def test_load_proxy_simple():
    cat3 = _cwl_tool_path("draft2/cat3-tool.cwl")
    tool_source = get_tool_source(cat3)

    assert tool_source.parse_description() == "Print the contents of a file to stdout using 'cat' running in a docker container."

    input_sources = _inputs(tool_source)
    assert len(input_sources) == 1

    input_source = input_sources[0]
    assert input_source.parse_help() == "The file to cat"
    assert input_source.parse_label() == "Input File"

    outputs, output_collections = tool_source.parse_outputs(None)
    assert len(outputs) == 1

    _, containers = tool_source.parse_requirements_and_containers()
    assert len(containers) == 1


def test_load_proxy_bwa_mem():
    bwa_mem = _cwl_tool_path("draft2/bwa-mem-tool.cwl")
    tool_source = get_tool_source(bwa_mem)
    _inputs(tool_source)


def test_env_tool1():
    env_tool1 = _cwl_tool_path("draft2/env-tool1.cwl")
    tool_source = get_tool_source(env_tool1)
    _inputs(tool_source)


def test_sorttool():
    env_tool1 = _cwl_tool_path("draft2/sorttool.cwl")
    tool_source = get_tool_source(env_tool1)
    _inputs(tool_source)


def _inputs(tool_source):
    input_pages = tool_source.parse_input_pages()
    assert input_pages.inputs_defined
    page_sources = input_pages.page_sources
    assert len(page_sources) == 1
    page_source = page_sources[0]
    input_sources = page_source.parse_input_sources()
    return input_sources


def _cwl_tool_path(path):
    return os.path.join(CWL_TOOLS_DIRECTORY, path)
