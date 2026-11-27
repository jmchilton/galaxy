import glob
import os
from pathlib import Path

import pytest

from galaxy.tool_util.parser import get_tool_source
from galaxy.tool_util.unittest_utils import functional_test_tool_path
from galaxy.tools import security_refusal
from galaxy.tools.security_refusal import (
    built_tool_type,
    GALAXY_OWN_TOOL,
    is_galaxy_own_tool,
    is_galaxy_upload_tool,
    review_exclusion,
    ToolInputRejected,
)
from galaxy.tools.special_tools import hidden_lib_tool_paths
from galaxy.util import galaxy_directory

TOOLS_DIR = os.path.dirname(security_refusal.__file__)
GALAXY_UPLOAD_TOOL = os.path.join(TOOLS_DIR, "bundled", "data_source", "upload.xml")


def _lib(*parts: str) -> str:
    return os.path.join(os.path.dirname(TOOLS_DIR), *parts)


def test_galaxy_runs_five_tools_as_its_own_machinery() -> None:
    names = sorted(os.path.relpath(path, os.path.dirname(TOOLS_DIR)) for path in hidden_lib_tool_paths())
    assert names == [
        "datatypes/set_metadata_tool.xml",
        "tools/data_fetch.xml",
        "tools/imp_exp/exp_history_to_archive.xml",
        "tools/imp_exp/exp_history_to_uri.xml",
        "tools/imp_exp/imp_history_from_archive.xml",
    ]
    assert all(os.path.exists(path) for path in hidden_lib_tool_paths())


@pytest.mark.parametrize(
    "path",
    [
        GALAXY_UPLOAD_TOOL,
        # The functional test tools link to it.
        functional_test_tool_path("upload.xml"),
        # The directory bundled links to in a source checkout, as its tool conf loads it.
        os.path.realpath(GALAXY_UPLOAD_TOOL),
        _lib("datatypes", "set_metadata_tool.xml"),
        _lib("tools", "data_fetch.xml"),
        _lib("tools", "imp_exp", "exp_history_to_archive.xml"),
        _lib("tools", "imp_exp", "exp_history_to_uri.xml"),
        _lib("tools", "imp_exp", "imp_history_from_archive.xml"),
        # Not normalized, as a tool conf may give it.
        os.path.join(TOOLS_DIR, "imp_exp", "..", "data_fetch.xml"),
    ],
    ids=lambda path: os.path.relpath(path, os.path.dirname(TOOLS_DIR)),
)
def test_galaxy_own_tools(path: str) -> None:
    assert is_galaxy_own_tool(path)
    assert is_galaxy_upload_tool(path) == (os.path.basename(path) == "upload.xml")
    # Once a tool patch applies, it is not the tool Galaxy ships.
    assert not is_galaxy_own_tool(path, patched=True)


@pytest.mark.parametrize(
    "path",
    [
        # Collection operations and sample sheet tools, though they sit beside data fetch.
        _lib("tools", "unzip_collection.xml"),
        _lib("tools", "sample_sheet_to_tabular.xml"),
        _lib("tools", "convert_sample_sheet.xml"),
        _lib("datatypes", "converters", "bam_to_bai.xml"),
        # Stock tools, through bundled and through the directory it links to in a source checkout.
        _lib("tools", "bundled", "filters", "catWrapper.xml"),
        os.path.realpath(_lib("tools", "bundled", "filters", "catWrapper.xml")),
        _lib("tools", "bundled", "data_source", "upload.py"),
        _lib("tool_util", "security", "spec", "tools", "command_position.xml"),
        functional_test_tool_path("simple_constructs.xml"),
    ],
    ids=lambda path: os.path.relpath(path, os.path.dirname(TOOLS_DIR)),
)
def test_other_tools_galaxy_ships_are_reviewed(path: str) -> None:
    assert os.path.exists(path)
    assert not is_galaxy_own_tool(path)
    assert not is_galaxy_upload_tool(path)


def test_own_tools_resolve_beside_the_real_tools_directory(tmp_path: Path) -> None:
    # The packages link galaxy/tools to lib/galaxy/tools: set metadata's ../datatypes exists only beside the target.
    (tmp_path / "lib" / "tools").mkdir(parents=True)
    (tmp_path / "lib" / "datatypes").mkdir()
    (tmp_path / "lib" / "datatypes" / "set_metadata_tool.xml").write_text("<tool/>")
    (tmp_path / "package").mkdir()
    linked = tmp_path / "package" / "tools"
    linked.symlink_to(tmp_path / "lib" / "tools")
    set_metadata = os.path.abspath(os.path.join(linked, "..", "datatypes", "set_metadata_tool.xml"))
    assert not os.path.exists(set_metadata)
    resolved = security_refusal._real_lib_path(set_metadata, str(linked))
    assert resolved == os.path.realpath(tmp_path / "lib" / "datatypes" / "set_metadata_tool.xml")


def test_copies_of_galaxy_own_tools_are_reviewed(tmp_path: Path) -> None:
    for path in (GALAXY_UPLOAD_TOOL, _lib("tools", "data_fetch.xml")):
        copy = tmp_path / os.path.basename(path)
        copy.write_text(Path(path).read_text())
        assert not is_galaxy_own_tool(copy)
        assert not is_galaxy_upload_tool(copy)
    assert not is_galaxy_own_tool(None)
    assert not is_galaxy_upload_tool(None)


def _exclusion(path: str | Path) -> str | None:
    reason: str | None = review_exclusion(path, built_tool_type(get_tool_source(str(path))))
    return reason


# Galaxy builds a tool as the class a <type> element names, whatever its tool_type says.
TYPED_TOOL = """<tool id="typed" name="typed" version="1.0" TOOL_TYPE>
    <type class="CLASS" module="galaxy.tools"/>
    <command>echo $word > '$out'</command>
    <inputs><param name="word" type="text"/></inputs>
    <outputs><data name="out" format="txt"/></outputs>
</tool>
"""


@pytest.mark.parametrize(
    "tool_type,tool_class,reason",
    [
        ("", "InteractiveTool", "it is an interactive tool"),
        ('tool_type="interactive"', "Tool", None),
        ('tool_type="cwl"', "Tool", None),
    ],
    ids=["interactive_class", "interactive_overridden", "cwl_overridden"],
)
def test_review_exclusion_follows_the_class_galaxy_builds(
    tmp_path: Path, tool_type: str, tool_class: str, reason: str | None
) -> None:
    tool = tmp_path / "typed.xml"
    tool.write_text(TYPED_TOOL.replace("TOOL_TYPE", tool_type).replace("CLASS", tool_class))
    assert _exclusion(tool) == reason


@pytest.mark.parametrize(
    "path,reason",
    [
        (functional_test_tool_path("interactivetool_simple.xml"), "it is an interactive tool"),
        (functional_test_tool_path("parameters/cwl_int.cwl"), "it is a CWL tool"),
        (GALAXY_UPLOAD_TOOL, GALAXY_OWN_TOOL),
        # No tool_type.
        (functional_test_tool_path("simple_constructs.xml"), None),
        # Another tool_type.
        (_lib("tools", "bundled", "data_source", "ucsc_tablebrowser.xml"), None),
    ],
    ids=lambda value: os.path.basename(value) if isinstance(value, str) and os.sep in value else None,
)
def test_review_exclusion(path: str, reason: str | None) -> None:
    assert _exclusion(path) == reason


def test_xml_that_claims_cwl_is_reviewed(tmp_path: Path) -> None:
    # Galaxy does not build it (only CWL sources are CWL tools), so nothing is left out.
    tool = tmp_path / "claims_cwl.xml"
    tool.write_text(
        TYPED_TOOL.replace("TOOL_TYPE", 'tool_type="cwl"').replace('<type class="CLASS" module="galaxy.tools"/>', "")
    )
    assert built_tool_type(get_tool_source(str(tool))) is None
    assert _exclusion(tool) is None


def test_galaxy_interactive_tools_are_excluded() -> None:
    interactive = glob.glob(os.path.join(galaxy_directory(), "tools", "interactive", "*.xml"))
    interactive += glob.glob(functional_test_tool_path("interactivetool_*.xml"))
    assert len(interactive) > 40
    assert {path: _exclusion(path) for path in interactive} == dict.fromkeys(interactive, "it is an interactive tool")


def test_interactive_tools_are_excluded_in_any_tool_format(tmp_path: Path) -> None:
    tool = tmp_path / "interactive.yml"
    tool.write_text(
        "class: GalaxyTool\nid: interactive_yaml\nname: interactive_yaml\nversion: '1.0'\n"
        "tool_type: interactive\ncommand: echo $word\ninputs: []\noutputs: {}\n"
    )
    assert _exclusion(tool) == "it is an interactive tool"


def test_tools_with_entry_points_but_no_interactive_type_are_reviewed(tmp_path: Path) -> None:
    source = Path(functional_test_tool_path("interactivetool_simple.xml")).read_text()
    assert ' tool_type="interactive"' in source and "<entry_points>" in source
    tool = tmp_path / "lookalike.xml"
    tool.write_text(source.replace(' tool_type="interactive"', ""))
    assert built_tool_type(get_tool_source(str(tool))) == "default"
    assert _exclusion(tool) is None


def test_a_patch_lifts_only_the_own_tool_exclusion() -> None:
    assert review_exclusion(GALAXY_UPLOAD_TOOL, None, patched=True) is None
    # A tool patch does not change the class Galaxy builds a tool as.
    assert review_exclusion(GALAXY_UPLOAD_TOOL, "interactive", patched=True) == "it is an interactive tool"
    assert review_exclusion(None, "cwl", patched=True) == "it is a CWL tool"
    assert review_exclusion(None, None) is None


def test_refusal_names_its_codes_first() -> None:
    assert str(ToolInputRejected("This job was not run.", ["b-code", "a-code", "b-code"])) == (
        "[a-code, b-code] This job was not run."
    )
    assert ToolInputRejected("This job was not run.", ["b-code", "a-code"]).codes == ("a-code", "b-code")
    assert str(ToolInputRejected("This job was not run.")) == "This job was not run."
