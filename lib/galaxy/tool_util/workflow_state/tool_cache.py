"""CLI entry point for galaxy-tool-cache.

Manages a local cache of ParsedTool metadata for ToolShed tools.
Supports population from ToolShed API, GitHub, or local XML files.

Usage:
    galaxy-tool-cache populate-workflow workflow.ga [--source api|github] [--cache-dir DIR]
    galaxy-tool-cache add TOOL_ID --version VERSION [--source api|github]
    galaxy-tool-cache add-local /path/to/tool.xml --tool-id TOOL_ID
    galaxy-tool-cache list [--json]
    galaxy-tool-cache info TRS_TOOL_ID --version VERSION
    galaxy-tool-cache clear [TOOL_ID_PREFIX]
"""

import argparse
import json
import logging
import sys
from typing import Optional

from galaxy.tool_util.workflow_state.toolshed_tool_info import (
    parse_toolshed_tool_id,
    ToolShedGetToolInfo,
)

log = logging.getLogger(__name__)


def _get_tool_info(cache_dir: Optional[str] = None) -> ToolShedGetToolInfo:
    return ToolShedGetToolInfo(cache_dir=cache_dir)


def _add_tool(tool_info: ToolShedGetToolInfo, tool_id: str, tool_version: Optional[str],
              source: str = "auto") -> bool:
    """Add a single tool to the cache. Returns True on success."""
    parsed = parse_toolshed_tool_id(tool_id)
    if parsed is None:
        print(f"  SKIP {tool_id} (not a toolshed tool)")
        return False

    toolshed_url, trs_tool_id, embedded_version = parsed
    version = tool_version or embedded_version
    if version is None:
        print(f"  SKIP {tool_id} (no version available)")
        return False

    # Check if already cached
    if tool_info.has_cached(tool_id, version):
        print(f"  CACHED {tool_id} {version}")
        return True

    # Try sources based on preference
    sources_to_try = []
    if source == "auto":
        sources_to_try = ["api", "github"]
    else:
        sources_to_try = [source]

    for src in sources_to_try:
        try:
            if src == "api":
                parsed_tool = tool_info.fetch_from_api(toolshed_url, trs_tool_id, version)
                source_url = f"{toolshed_url}/api/tools/{trs_tool_id}/versions/{version}"
            elif src == "github":
                from galaxy.tool_util.workflow_state.toolshed_github import parse_tool_from_github
                parts = trs_tool_id.split("~")
                owner, repo, tool_name = parts[0], parts[1], parts[2]
                parsed_tool, source_url = parse_tool_from_github(owner, repo, tool_name, version)
            else:
                continue

            from galaxy.tool_util.workflow_state.toolshed_tool_info import _tool_id_from_trs
            readable_id = _tool_id_from_trs(toolshed_url, trs_tool_id)
            tool_info.populate_from_parsed_tool(tool_id, version, parsed_tool, source=src, source_url=source_url)
            print(f"  OK {tool_id} {version} (from {src})")
            return True
        except Exception as e:
            log.debug(f"  Failed to fetch {tool_id} {version} from {src}: {e}")
            continue

    print(f"  FAIL {tool_id} {version}")
    return False


def cmd_populate_workflow(args):
    """Cache all ToolShed tools needed by a workflow."""
    from galaxy.tool_util.workflow_state.workflow_tools import (
        extract_toolshed_tools,
        load_workflow,
    )

    tool_info = _get_tool_info(args.cache_dir)
    workflow = load_workflow(args.workflow_path)
    tools = extract_toolshed_tools(workflow)

    if not tools:
        print("No ToolShed tools found in workflow.")
        return

    print(f"Found {len(tools)} ToolShed tool(s) in workflow:")
    ok = 0
    fail = 0
    for tool_id, tool_version in tools:
        if _add_tool(tool_info, tool_id, tool_version, source=args.source):
            ok += 1
        else:
            fail += 1

    print(f"\nSummary: {ok} cached, {fail} failed")


def cmd_add(args):
    """Cache a single tool."""
    tool_info = _get_tool_info(args.cache_dir)
    _add_tool(tool_info, args.tool_id, args.version, source=args.source)


def cmd_add_local(args):
    """Cache a tool from a local XML file."""
    from galaxy.tool_util.model_factory import parse_tool
    from galaxy.tool_util.parser.factory import get_tool_source

    tool_info = _get_tool_info(args.cache_dir)

    try:
        tool_source = get_tool_source(config_file=args.xml_path)
        parsed_tool = parse_tool(tool_source)
    except Exception as e:
        print(f"Failed to parse {args.xml_path}: {e}", file=sys.stderr)
        sys.exit(1)

    tool_id = args.tool_id
    # If no explicit tool_id, try to construct one from parsed info
    if tool_id is None:
        parsed_id = parsed_tool.id
        parsed_version = parsed_tool.version
        if parsed_id and parsed_version:
            print(f"Parsed tool: {parsed_id} v{parsed_version}")
            print("Use --tool-id to specify the full toolshed tool_id for proper cache keying.")
            sys.exit(1)
        else:
            print("Cannot determine tool_id from XML. Use --tool-id.", file=sys.stderr)
            sys.exit(1)

    version = args.version or parsed_tool.version
    if version is None:
        print("Cannot determine version. Use --version.", file=sys.stderr)
        sys.exit(1)

    tool_info.populate_from_parsed_tool(tool_id, version, parsed_tool,
                                        source="local", source_url=str(args.xml_path))
    print(f"Cached {tool_id} {version} from {args.xml_path}")


def cmd_list(args):
    """List cached tools."""
    tool_info = _get_tool_info(args.cache_dir)
    entries = tool_info.list_cached()

    if not entries:
        print("Cache is empty.")
        return

    if args.json:
        print(json.dumps(entries, indent=2))
    else:
        # Table format
        print(f"{'Tool ID':<60} {'Version':<20} {'Source':<8} {'Cached At':<11}")
        print("-" * 100)
        for entry in entries:
            tool_id = entry.get("tool_id", "?")
            version = entry.get("tool_version", "?")
            source = entry.get("source", "?")
            cached_at = entry.get("cached_at", "?")[:10]
            print(f"{tool_id:<60} {version:<20} {source:<8} {cached_at:<11}")
        print(f"\n{len(entries)} tool(s) cached.")


def cmd_info(args):
    """Show details for a cached tool."""
    tool_info = _get_tool_info(args.cache_dir)

    # Find matching entries
    entries = tool_info.list_cached()
    matches = []
    for entry in entries:
        tid = entry.get("tool_id", "")
        tver = entry.get("tool_version", "")
        if args.trs_tool_id in tid:
            if args.version is None or tver == args.version:
                matches.append(entry)

    if not matches:
        print(f"No cached entries matching '{args.trs_tool_id}'")
        sys.exit(1)

    for entry in matches:
        print(f"Tool ID:   {entry.get('tool_id', '?')}")
        print(f"Version:   {entry.get('tool_version', '?')}")
        print(f"Source:    {entry.get('source', '?')}")
        print(f"Source URL:{entry.get('source_url', '')}")
        print(f"Cached at: {entry.get('cached_at', '?')}")
        print(f"Cache key: {entry.get('cache_key', '?')}")

        # Load and show summary from the ParsedTool
        cache_key = entry.get("cache_key")
        if cache_key:
            parsed = tool_info.load_cached(cache_key)
            if parsed:
                print(f"Name:      {parsed.name}")
                print(f"Inputs:    {len(parsed.inputs)} parameter(s)")
                print(f"Outputs:   {len(parsed.outputs)} output(s)")
        print()


def cmd_clear(args):
    """Clear cache."""
    tool_info = _get_tool_info(args.cache_dir)
    if args.tool_id_prefix:
        tool_info.clear_cache(args.tool_id_prefix)
        print(f"Cleared cache entries matching '{args.tool_id_prefix}'")
    else:
        tool_info.clear_cache()
        print("Cache cleared.")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="galaxy-tool-cache",
        description="Manage local cache of ToolShed tool metadata for workflow validation.",
    )
    parser.add_argument("--cache-dir", help="Cache directory (default: $GALAXY_TOOL_CACHE_DIR or ~/.galaxy/tool_info_cache/)")
    parser.add_argument("-v", "--verbose", action="store_true", help="Enable verbose logging")

    subparsers = parser.add_subparsers(dest="command", required=True)

    # populate-workflow
    p_pop = subparsers.add_parser("populate-workflow", help="Cache all ToolShed tools in a workflow")
    p_pop.add_argument("workflow_path", help="Path to .ga or .gxwf.yml workflow file")
    p_pop.add_argument("--source", choices=["auto", "api", "github"], default="auto",
                       help="Source preference (default: auto = try api then github)")
    p_pop.set_defaults(func=cmd_populate_workflow)

    # add
    p_add = subparsers.add_parser("add", help="Cache a single ToolShed tool")
    p_add.add_argument("tool_id", help="Full tool_id or TRS-style ID")
    p_add.add_argument("--version", help="Tool version (if not embedded in tool_id)")
    p_add.add_argument("--source", choices=["auto", "api", "github"], default="auto")
    p_add.set_defaults(func=cmd_add)

    # add-local
    p_local = subparsers.add_parser("add-local", help="Cache from a local XML file")
    p_local.add_argument("xml_path", help="Path to tool XML file")
    p_local.add_argument("--tool-id", dest="tool_id",
                         help="Full toolshed tool_id (e.g. toolshed.g2.bx.psu.edu/repos/devteam/fastqc/fastqc/0.74+galaxy0)")
    p_local.add_argument("--version", help="Tool version (overrides parsed version)")
    p_local.set_defaults(func=cmd_add_local)

    # list
    p_list = subparsers.add_parser("list", help="List cached tools")
    p_list.add_argument("--json", action="store_true", help="Output as JSON")
    p_list.set_defaults(func=cmd_list)

    # info
    p_info = subparsers.add_parser("info", help="Show cached tool details")
    p_info.add_argument("trs_tool_id", help="TRS tool ID or substring to match")
    p_info.add_argument("--version", help="Filter by version")
    p_info.set_defaults(func=cmd_info)

    # clear
    p_clear = subparsers.add_parser("clear", help="Clear cache")
    p_clear.add_argument("tool_id_prefix", nargs="?", help="Clear entries matching this prefix (default: clear all)")
    p_clear.set_defaults(func=cmd_clear)

    return parser


def main(argv=None):
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.verbose:
        logging.basicConfig(level=logging.DEBUG)
    else:
        logging.basicConfig(level=logging.WARNING)

    args.func(args)


if __name__ == "__main__":
    main()
