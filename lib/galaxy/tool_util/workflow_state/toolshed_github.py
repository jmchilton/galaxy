"""Download and parse tool XML from GitHub repositories.

Resolves ToolShed owner/repo to GitHub repositories, downloads tool XML
and macro files, parses locally with get_tool_source() + parse_tool().
"""

import json
import logging
import os
import shutil
import tempfile
import urllib.request
from typing import (
    Dict,
    List,
    Optional,
    Tuple,
)
from xml.etree import ElementTree

from galaxy.tool_util.model_factory import parse_tool
from galaxy.tool_util.parser.factory import get_tool_source
from galaxy.tool_util_models import ParsedTool

log = logging.getLogger(__name__)

# Known ToolShed owner → GitHub org/repo mappings.
# Fallback: try {owner}/{repo} on GitHub.
OWNER_REPO_MAP: Dict[str, str] = {
    "iuc": "galaxyproject/tools-iuc",
    "devteam": "galaxyproject/tools-devteam",
    "bgruening": "bgruening/galaxytools",
}

GITHUB_RAW_BASE = "https://raw.githubusercontent.com"
GITHUB_API_BASE = "https://api.github.com"


def resolve_github_repo(owner: str, repo: str) -> str:
    """Map ToolShed owner/repo to GitHub org/repo string.

    Returns e.g. 'galaxyproject/tools-iuc'.
    """
    if owner in OWNER_REPO_MAP:
        return OWNER_REPO_MAP[owner]
    return f"{owner}/{repo}"


def _github_api_search_tool(github_repo: str, tool_name: str, token: Optional[str] = None) -> Optional[str]:
    """Search GitHub repo for a tool XML matching tool_name.

    Returns the path within the repo (e.g. 'tools/fastqc/rgFastQC.xml') or None.
    Uses the GitHub code search API.
    """
    # Search for XML files containing the tool id
    url = f"{GITHUB_API_BASE}/search/code?q=tool+id+%22{tool_name}%22+repo:{github_repo}+extension:xml"
    headers = {"Accept": "application/vnd.github.v3+json"}
    if token:
        headers["Authorization"] = f"token {token}"
    try:
        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read().decode())
        for item in data.get("items", []):
            path = item.get("path", "")
            if path.endswith(".xml") and tool_name in path:
                return path
        # If no exact path match, return first XML result
        if data.get("items"):
            return data["items"][0]["path"]
    except Exception as e:
        log.debug(f"GitHub API search failed for {tool_name} in {github_repo}: {e}")
    return None


def _find_tool_xml_by_convention(github_repo: str, owner: str, repo: str, tool_name: str,
                                 branch: str = "main") -> List[str]:
    """Generate candidate paths for a tool XML in a GitHub repo.

    Most Galaxy tool repos follow predictable directory structures.
    """
    candidates = []

    # Common patterns in tools-iuc/tools-devteam style repos
    # tools/{repo_name}/{tool_name}.xml
    candidates.append(f"tools/{repo}/{tool_name}.xml")
    # tools/{tool_name}/{tool_name}.xml
    candidates.append(f"tools/{tool_name}/{tool_name}.xml")
    # {repo_name}/{tool_name}.xml (bgruening style — tools in subdirs of repo name)
    candidates.append(f"{repo}/{tool_name}.xml")
    # Root level
    candidates.append(f"{tool_name}.xml")

    return candidates


def _download_raw(github_repo: str, path: str, dest: str, branch: str = "main",
                  token: Optional[str] = None) -> bool:
    """Download a raw file from GitHub to dest path."""
    url = f"{GITHUB_RAW_BASE}/{github_repo}/{branch}/{path}"
    headers = {}
    if token:
        headers["Authorization"] = f"token {token}"
    try:
        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req, timeout=30) as resp:
            content = resp.read()
        os.makedirs(os.path.dirname(dest), exist_ok=True)
        with open(dest, "wb") as f:
            f.write(content)
        return True
    except Exception as e:
        log.debug(f"Failed to download {url}: {e}")
        return False


def _extract_macro_imports(xml_path: str) -> List[str]:
    """Extract <import> filenames from <macros> section of a tool XML."""
    imports = []
    try:
        tree = ElementTree.parse(xml_path)
        for macros_elem in tree.iter("macros"):
            for import_elem in macros_elem.iter("import"):
                if import_elem.text:
                    imports.append(import_elem.text.strip())
    except Exception as e:
        log.debug(f"Failed to parse macros from {xml_path}: {e}")
    return imports


def download_tool_with_macros(
    github_repo: str,
    tool_xml_path: str,
    branch: str = "main",
    token: Optional[str] = None,
) -> Tuple[Optional[str], Optional[str]]:
    """Download tool XML and its macro imports to a temp directory.

    Returns (temp_dir, local_xml_path) or (None, None) on failure.
    The caller is responsible for cleaning up temp_dir.
    """
    work_dir = tempfile.mkdtemp(prefix="galaxy-tool-cache-")
    tool_dir = os.path.dirname(tool_xml_path)
    tool_filename = os.path.basename(tool_xml_path)

    # Download tool XML
    local_xml = os.path.join(work_dir, tool_filename)
    if not _download_raw(github_repo, tool_xml_path, local_xml, branch, token):
        return None, None

    # Extract and download macro imports
    macro_imports = _extract_macro_imports(local_xml)
    for macro_file in macro_imports:
        # Macros are relative to the tool XML's directory
        remote_macro_path = f"{tool_dir}/{macro_file}" if tool_dir else macro_file
        local_macro = os.path.join(work_dir, macro_file)
        if not _download_raw(github_repo, remote_macro_path, local_macro, branch, token):
            log.warning(f"Failed to download macro {macro_file} for {tool_xml_path}")
            # Continue — some macros may be optional or the tool may still parse

    return work_dir, local_xml


def parse_tool_from_github(
    owner: str,
    repo: str,
    tool_name: str,
    tool_version: Optional[str] = None,
    branch: str = "main",
    token: Optional[str] = None,
) -> Tuple[ParsedTool, str]:
    """Download and parse a tool from GitHub.

    Returns (ParsedTool, source_url).
    Raises KeyError if the tool cannot be found or parsed.
    """
    github_repo = resolve_github_repo(owner, repo)
    github_token = token or os.environ.get("GITHUB_TOKEN")

    # Try to find the tool XML
    tool_xml_path = None

    # First try API search (if we have a token or are willing to use unauthenticated quota)
    if github_token:
        tool_xml_path = _github_api_search_tool(github_repo, tool_name, github_token)

    # Fall back to convention-based paths
    if tool_xml_path is None:
        candidates = _find_tool_xml_by_convention(github_repo, owner, repo, tool_name, branch)
        for candidate in candidates:
            url = f"{GITHUB_RAW_BASE}/{github_repo}/{branch}/{candidate}"
            try:
                req = urllib.request.Request(url, method="HEAD")
                with urllib.request.urlopen(req, timeout=10):
                    tool_xml_path = candidate
                    break
            except Exception:
                continue

    if tool_xml_path is None:
        raise KeyError(f"Could not find tool XML for {tool_name} in {github_repo}")

    # Download tool + macros
    work_dir, local_xml = download_tool_with_macros(github_repo, tool_xml_path, branch, github_token)
    if work_dir is None or local_xml is None:
        raise KeyError(f"Failed to download tool XML from {github_repo}/{tool_xml_path}")

    try:
        tool_source = get_tool_source(config_file=local_xml)
        parsed_tool = parse_tool(tool_source)
        source_url = f"{GITHUB_RAW_BASE}/{github_repo}/{branch}/{tool_xml_path}"
        return parsed_tool, source_url
    except Exception as e:
        raise KeyError(f"Failed to parse tool from {github_repo}/{tool_xml_path}: {e}")
    finally:
        shutil.rmtree(work_dir, ignore_errors=True)
