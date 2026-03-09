"""Tests for tool cache infrastructure: index, workflow extraction, CLI."""

import json
import os
import tempfile

import pytest

from galaxy.tool_util.workflow_state.toolshed_tool_info import (
    _cache_key,
    CacheIndex,
    get_cache_dir,
    parse_toolshed_tool_id,
    ToolShedGetToolInfo,
)
from galaxy.tool_util.workflow_state.workflow_tools import (
    extract_toolshed_tools,
    load_workflow,
)
from galaxy.tool_util.workflow_state.tool_cache import build_parser


# --- parse_toolshed_tool_id ---

class TestParseToolshedToolId:
    def test_full_id_with_version(self):
        result = parse_toolshed_tool_id(
            "toolshed.g2.bx.psu.edu/repos/devteam/fastqc/fastqc/0.74+galaxy0"
        )
        assert result is not None
        url, trs_id, version = result
        assert url == "https://toolshed.g2.bx.psu.edu"
        assert trs_id == "devteam~fastqc~fastqc"
        assert version == "0.74+galaxy0"

    def test_full_id_with_scheme(self):
        result = parse_toolshed_tool_id(
            "https://toolshed.g2.bx.psu.edu/repos/iuc/multiqc/multiqc/1.11+galaxy1"
        )
        assert result is not None
        url, trs_id, version = result
        assert url == "https://toolshed.g2.bx.psu.edu"
        assert trs_id == "iuc~multiqc~multiqc"
        assert version == "1.11+galaxy1"

    def test_id_without_version(self):
        result = parse_toolshed_tool_id(
            "toolshed.g2.bx.psu.edu/repos/devteam/fastqc/fastqc"
        )
        assert result is not None
        url, trs_id, version = result
        assert trs_id == "devteam~fastqc~fastqc"
        assert version is None

    def test_not_a_toolshed_tool(self):
        assert parse_toolshed_tool_id("cat1") is None
        assert parse_toolshed_tool_id("__DATA_FETCH__") is None
        assert parse_toolshed_tool_id("upload1") is None

    def test_too_few_segments(self):
        assert parse_toolshed_tool_id("toolshed.g2.bx.psu.edu/repos/owner/repo") is None


# --- CacheIndex ---

class TestCacheIndex:
    def test_add_and_list(self, tmp_path):
        index = CacheIndex(str(tmp_path))
        index.add("abc123", "devteam/fastqc", "0.74", "api", "https://...")
        entries = index.list_all()
        assert len(entries) == 1
        assert entries[0]["cache_key"] == "abc123"
        assert entries[0]["tool_id"] == "devteam/fastqc"
        assert entries[0]["source"] == "api"

    def test_has(self, tmp_path):
        index = CacheIndex(str(tmp_path))
        assert not index.has("abc123")
        index.add("abc123", "test", "1.0", "api")
        assert index.has("abc123")

    def test_remove(self, tmp_path):
        index = CacheIndex(str(tmp_path))
        index.add("abc123", "test", "1.0", "api")
        index.remove("abc123")
        assert not index.has("abc123")

    def test_clear(self, tmp_path):
        index = CacheIndex(str(tmp_path))
        index.add("a", "t1", "1.0", "api")
        index.add("b", "t2", "2.0", "github")
        index.clear()
        assert len(index.list_all()) == 0

    def test_persistence(self, tmp_path):
        index1 = CacheIndex(str(tmp_path))
        index1.add("abc", "tool", "1.0", "api")

        # New instance reads from disk
        index2 = CacheIndex(str(tmp_path))
        assert index2.has("abc")
        entries = index2.list_all()
        assert len(entries) == 1

    def test_corrupted_index_recovers(self, tmp_path):
        # Write invalid JSON
        index_path = os.path.join(str(tmp_path), "index.json")
        with open(index_path, "w") as f:
            f.write("{bad json")

        index = CacheIndex(str(tmp_path))
        assert len(index.list_all()) == 0
        # Can still add
        index.add("new", "tool", "1.0", "api")
        assert index.has("new")


# --- get_cache_dir ---

class TestGetCacheDir:
    def test_override(self):
        assert get_cache_dir("/custom/path") == "/custom/path"

    def test_env_var(self, monkeypatch):
        monkeypatch.setenv("GALAXY_TOOL_CACHE_DIR", "/env/path")
        assert get_cache_dir() == "/env/path"

    def test_default(self, monkeypatch):
        monkeypatch.delenv("GALAXY_TOOL_CACHE_DIR", raising=False)
        result = get_cache_dir()
        assert result.endswith("tool_info_cache")


# --- ToolShedGetToolInfo cache operations ---

class TestToolShedGetToolInfoCache:
    def _make_fake_parsed_tool(self):
        """Create a minimal ParsedTool for testing."""
        from galaxy.tool_util_models import ParsedTool
        return ParsedTool(
            id="fastqc",
            version="0.74+galaxy0",
            name="FastQC",
            description="Read Quality reports",
            inputs=[],
            outputs=[],
            citations=[],
            license=None,
            profile=None,
            edam_operations=[],
            edam_topics=[],
            xrefs=[],
            help=None,
        )

    def test_populate_and_retrieve(self, tmp_path):
        tool_info = ToolShedGetToolInfo(cache_dir=str(tmp_path))
        pt = self._make_fake_parsed_tool()

        tool_id = "toolshed.g2.bx.psu.edu/repos/devteam/fastqc/fastqc/0.74+galaxy0"
        key = tool_info.populate_from_parsed_tool(tool_id, "0.74+galaxy0", pt, source="test")

        assert tool_info.has_cached(tool_id, "0.74+galaxy0")

        # Retrieve it
        result = tool_info.get_tool_info(tool_id, "0.74+galaxy0")
        assert result.name == "FastQC"

    def test_list_cached(self, tmp_path):
        tool_info = ToolShedGetToolInfo(cache_dir=str(tmp_path))
        pt = self._make_fake_parsed_tool()

        tool_info.populate_from_parsed_tool(
            "toolshed.g2.bx.psu.edu/repos/devteam/fastqc/fastqc/0.74+galaxy0",
            "0.74+galaxy0", pt, source="api"
        )

        entries = tool_info.list_cached()
        assert len(entries) == 1
        assert entries[0]["source"] == "api"

    def test_clear_all(self, tmp_path):
        tool_info = ToolShedGetToolInfo(cache_dir=str(tmp_path))
        pt = self._make_fake_parsed_tool()

        tool_info.populate_from_parsed_tool(
            "toolshed.g2.bx.psu.edu/repos/devteam/fastqc/fastqc/0.74+galaxy0",
            "0.74+galaxy0", pt, source="api"
        )
        tool_info.clear_cache()

        assert len(tool_info.list_cached()) == 0
        assert not tool_info.has_cached(
            "toolshed.g2.bx.psu.edu/repos/devteam/fastqc/fastqc/0.74+galaxy0", "0.74+galaxy0"
        )

    def test_backfill_index_on_load(self, tmp_path):
        """Cache files without index entries get backfilled on load."""
        tool_info = ToolShedGetToolInfo(cache_dir=str(tmp_path))
        pt = self._make_fake_parsed_tool()

        # Write cache file directly (no index entry)
        key = _cache_key("https://toolshed.g2.bx.psu.edu", "devteam~fastqc~fastqc", "0.74+galaxy0")
        cache_path = os.path.join(str(tmp_path), f"{key}.json")
        os.makedirs(str(tmp_path), exist_ok=True)
        with open(cache_path, "w") as f:
            f.write(pt.model_dump_json(indent=2))

        # New instance — load should backfill index
        tool_info2 = ToolShedGetToolInfo(cache_dir=str(tmp_path))
        result = tool_info2.get_tool_info(
            "toolshed.g2.bx.psu.edu/repos/devteam/fastqc/fastqc/0.74+galaxy0", "0.74+galaxy0"
        )
        assert result.name == "FastQC"
        assert tool_info2.index.has(key)


# --- extract_toolshed_tools ---

IWC_DIR = os.path.join(os.path.dirname(__file__), "..", "..", "workflows", "iwc")


class TestExtractToolshedTools:
    def test_native_workflow(self):
        workflow = {
            "steps": {
                "0": {"type": "data_input"},
                "1": {
                    "tool_id": "toolshed.g2.bx.psu.edu/repos/devteam/fastqc/fastqc/0.74+galaxy0",
                    "tool_version": "0.74+galaxy0",
                },
                "2": {
                    "tool_id": "cat1",
                    "tool_version": "1.0.0",
                },
            }
        }
        tools = extract_toolshed_tools(workflow)
        assert len(tools) == 1
        assert tools[0][0] == "toolshed.g2.bx.psu.edu/repos/devteam/fastqc/fastqc/0.74+galaxy0"

    def test_format2_workflow(self):
        workflow = {
            "steps": [
                {"type": "data_input"},
                {
                    "tool_id": "toolshed.g2.bx.psu.edu/repos/iuc/multiqc/multiqc/1.11+galaxy1",
                    "tool_version": "1.11+galaxy1",
                },
            ]
        }
        tools = extract_toolshed_tools(workflow)
        assert len(tools) == 1

    def test_subworkflow_recursion_native(self):
        workflow = {
            "steps": {
                "0": {
                    "type": "subworkflow",
                    "subworkflow": {
                        "steps": {
                            "0": {
                                "tool_id": "toolshed.g2.bx.psu.edu/repos/iuc/bwa/bwa/0.7.17",
                                "tool_version": "0.7.17",
                            }
                        }
                    },
                },
            }
        }
        tools = extract_toolshed_tools(workflow)
        assert len(tools) == 1
        assert "bwa" in tools[0][0]

    def test_deduplication(self):
        workflow = {
            "steps": {
                "0": {
                    "tool_id": "toolshed.g2.bx.psu.edu/repos/devteam/fastqc/fastqc/0.74+galaxy0",
                    "tool_version": "0.74+galaxy0",
                },
                "1": {
                    "tool_id": "toolshed.g2.bx.psu.edu/repos/devteam/fastqc/fastqc/0.74+galaxy0",
                    "tool_version": "0.74+galaxy0",
                },
            }
        }
        tools = extract_toolshed_tools(workflow)
        assert len(tools) == 1

    def test_no_toolshed_tools(self):
        workflow = {"steps": {"0": {"tool_id": "cat1", "tool_version": "1.0.0"}}}
        tools = extract_toolshed_tools(workflow)
        assert len(tools) == 0

    @pytest.mark.skipif(
        not os.path.exists(os.path.join(IWC_DIR, "RepeatMasking-Workflow.ga")),
        reason="IWC test workflows not available"
    )
    def test_iwc_repeat_masking(self):
        workflow = load_workflow(os.path.join(IWC_DIR, "RepeatMasking-Workflow.ga"))
        tools = extract_toolshed_tools(workflow)
        assert len(tools) == 2
        tool_ids = [t[0] for t in tools]
        assert any("repeatmodeler" in tid for tid in tool_ids)
        assert any("repeatmasker" in tid for tid in tool_ids)


# --- CLI parser ---

class TestCLIParser:
    def test_populate_workflow(self):
        parser = build_parser()
        args = parser.parse_args(["populate-workflow", "test.ga"])
        assert args.command == "populate-workflow"
        assert args.workflow_path == "test.ga"
        assert args.source == "auto"

    def test_populate_workflow_with_source(self):
        parser = build_parser()
        args = parser.parse_args(["populate-workflow", "test.ga", "--source", "github"])
        assert args.source == "github"

    def test_add(self):
        parser = build_parser()
        args = parser.parse_args(["add", "devteam~fastqc~fastqc", "--version", "0.74+galaxy0"])
        assert args.command == "add"
        assert args.tool_id == "devteam~fastqc~fastqc"
        assert args.version == "0.74+galaxy0"

    def test_add_local(self):
        parser = build_parser()
        args = parser.parse_args(["add-local", "/path/to/tool.xml", "--tool-id", "toolshed.../fastqc/0.74"])
        assert args.xml_path == "/path/to/tool.xml"

    def test_list(self):
        parser = build_parser()
        args = parser.parse_args(["list"])
        assert args.command == "list"

    def test_list_json(self):
        parser = build_parser()
        args = parser.parse_args(["list", "--json"])
        assert args.json is True

    def test_clear(self):
        parser = build_parser()
        args = parser.parse_args(["clear"])
        assert args.command == "clear"

    def test_clear_with_prefix(self):
        parser = build_parser()
        args = parser.parse_args(["clear", "devteam~fastqc~*"])
        assert args.tool_id_prefix == "devteam~fastqc~*"


# --- GitHub module ---

class TestGitHubResolution:
    def test_resolve_known_owners(self):
        from galaxy.tool_util.workflow_state.toolshed_github import resolve_github_repo
        assert resolve_github_repo("iuc", "multiqc") == "galaxyproject/tools-iuc"
        assert resolve_github_repo("devteam", "fastqc") == "galaxyproject/tools-devteam"
        assert resolve_github_repo("bgruening", "galaxytools") == "bgruening/galaxytools"

    def test_resolve_unknown_owner(self):
        from galaxy.tool_util.workflow_state.toolshed_github import resolve_github_repo
        assert resolve_github_repo("someuser", "sometool") == "someuser/sometool"

    def test_find_candidates(self):
        from galaxy.tool_util.workflow_state.toolshed_github import _find_tool_xml_by_convention
        candidates = _find_tool_xml_by_convention("galaxyproject/tools-iuc", "iuc", "multiqc", "multiqc")
        assert any("tools/multiqc/multiqc.xml" in c for c in candidates)

    def test_extract_macro_imports(self, tmp_path):
        from galaxy.tool_util.workflow_state.toolshed_github import _extract_macro_imports
        xml_content = """<tool id="test" name="Test" version="1.0">
    <macros>
        <import>macros.xml</import>
        <import>other_macros.xml</import>
    </macros>
</tool>"""
        xml_path = os.path.join(str(tmp_path), "tool.xml")
        with open(xml_path, "w") as f:
            f.write(xml_content)

        imports = _extract_macro_imports(xml_path)
        assert imports == ["macros.xml", "other_macros.xml"]

    def test_extract_no_macros(self, tmp_path):
        from galaxy.tool_util.workflow_state.toolshed_github import _extract_macro_imports
        xml_content = '<tool id="test" name="Test" version="1.0"></tool>'
        xml_path = os.path.join(str(tmp_path), "tool.xml")
        with open(xml_path, "w") as f:
            f.write(xml_content)

        imports = _extract_macro_imports(xml_path)
        assert imports == []
