"""GetToolInfo implementation that fetches ParsedTool from ToolShed 2.0 API.

Supports the full Galaxy workflow tool_id format:
  toolshed.g2.bx.psu.edu/repos/owner/repo/tool_id/version

Converts to TRS-style API call:
  GET {toolshed_url}/api/tools/{owner~repo~tool_id}/versions/{version}

Results are cached locally as JSON files for offline reuse.
"""

import hashlib
import json
import logging
import os
import urllib.request
from typing import (
    Dict,
    Optional,
    Tuple,
)

from galaxy.tool_util_models import ParsedTool

log = logging.getLogger(__name__)

DEFAULT_CACHE_DIR = os.path.join(os.path.expanduser("~"), ".galaxy", "tool_info_cache")


def parse_toolshed_tool_id(tool_id: str) -> Optional[Tuple[str, str, str]]:
    """Parse a toolshed tool_id into (toolshed_url, trs_tool_id, tool_version).

    Input format: toolshed.g2.bx.psu.edu/repos/owner/repo/tool_name/version
    Or with scheme: https://toolshed.g2.bx.psu.edu/repos/owner/repo/tool_name/version

    Returns None if the tool_id is not a toolshed tool.
    """
    if "/repos/" not in tool_id:
        return None

    parts = tool_id.split("/repos/", 1)
    toolshed_base = parts[0]
    rest = parts[1]

    # rest is: owner/repo/tool_name/version (or owner/repo/tool_name without version)
    segments = rest.split("/")
    if len(segments) < 3:
        return None

    # owner/repo/tool_name are the TRS tool ID components
    owner = segments[0]
    repo = segments[1]
    tool_name = segments[2]
    trs_tool_id = f"{owner}~{repo}~{tool_name}"

    # Version may be the 4th segment or provided separately
    tool_version = segments[3] if len(segments) > 3 else None

    # Ensure toolshed base has a scheme
    if not toolshed_base.startswith("http"):
        toolshed_base = f"https://{toolshed_base}"

    return toolshed_base, trs_tool_id, tool_version


def _cache_key(toolshed_url: str, trs_tool_id: str, tool_version: str) -> str:
    """Generate a filesystem-safe cache key."""
    raw = f"{toolshed_url}/{trs_tool_id}/{tool_version}"
    return hashlib.sha256(raw.encode()).hexdigest()


class ToolShedGetToolInfo:
    """Fetches ParsedTool from ToolShed 2.0 API with local filesystem cache."""

    def __init__(self, cache_dir: Optional[str] = None):
        self.cache_dir = cache_dir or DEFAULT_CACHE_DIR
        self._memory_cache: Dict[str, ParsedTool] = {}

    def get_tool_info(self, tool_id: str, tool_version: Optional[str]) -> ParsedTool:
        parsed = parse_toolshed_tool_id(tool_id)
        if parsed is None:
            raise KeyError(f"Not a toolshed tool: {tool_id}")

        toolshed_url, trs_tool_id, embedded_version = parsed
        version = tool_version or embedded_version
        if version is None:
            raise KeyError(f"No version available for toolshed tool: {tool_id}")

        cache_key = _cache_key(toolshed_url, trs_tool_id, version)

        # Check memory cache
        if cache_key in self._memory_cache:
            return self._memory_cache[cache_key]

        # Check filesystem cache
        cached = self._load_from_cache(cache_key)
        if cached is not None:
            self._memory_cache[cache_key] = cached
            return cached

        # Fetch from API
        parsed_tool = self._fetch_from_api(toolshed_url, trs_tool_id, version)
        self._save_to_cache(cache_key, parsed_tool)
        self._memory_cache[cache_key] = parsed_tool
        return parsed_tool

    def _fetch_from_api(self, toolshed_url: str, trs_tool_id: str, tool_version: str) -> ParsedTool:
        url = f"{toolshed_url}/api/tools/{trs_tool_id}/versions/{tool_version}"
        log.info(f"Fetching tool info from {url}")
        try:
            req = urllib.request.Request(url, headers={"Accept": "application/json"})
            with urllib.request.urlopen(req, timeout=30) as resp:
                data = json.loads(resp.read().decode())
        except Exception as e:
            raise KeyError(f"Failed to fetch tool info from {url}: {e}")
        return ParsedTool.model_validate(data)

    def _cache_path(self, cache_key: str) -> str:
        return os.path.join(self.cache_dir, f"{cache_key}.json")

    def _load_from_cache(self, cache_key: str) -> Optional[ParsedTool]:
        path = self._cache_path(cache_key)
        if not os.path.exists(path):
            return None
        try:
            with open(path) as f:
                data = json.load(f)
            return ParsedTool.model_validate(data)
        except Exception:
            log.debug(f"Cache entry {path} invalid, ignoring")
            return None

    def _save_to_cache(self, cache_key: str, parsed_tool: ParsedTool):
        os.makedirs(self.cache_dir, exist_ok=True)
        path = self._cache_path(cache_key)
        try:
            with open(path, "w") as f:
                f.write(parsed_tool.model_dump_json(indent=2))
        except Exception:
            log.debug(f"Failed to write cache entry {path}")


class CombinedGetToolInfo:
    """GetToolInfo that tries stock tools first, then falls back to ToolShed API."""

    def __init__(self, stock_get_tool_info, toolshed_get_tool_info: Optional[ToolShedGetToolInfo] = None):
        self.stock = stock_get_tool_info
        self.toolshed = toolshed_get_tool_info or ToolShedGetToolInfo()

    def get_tool_info(self, tool_id: str, tool_version: Optional[str]) -> ParsedTool:
        # If it looks like a toolshed tool, try toolshed first
        if "/repos/" in tool_id:
            try:
                return self.toolshed.get_tool_info(tool_id, tool_version)
            except KeyError:
                pass

        # Try stock tools
        return self.stock.get_tool_info(tool_id, tool_version)
