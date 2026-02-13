"""Test that CWL tools produce valid ToolParameterBundleModels via factory pipeline.

For each CWL tool file, calls input_models_for_tool_source(get_tool_source(path))
and asserts it returns a ToolParameterBundleModel without raising. This validates
that _from_input_source_cwl() handles all CWL types used by each tool.

Three tiers:
  - parameter tools (test/functional/tools/parameters/cwl_*.cwl) — always available
  - v1.0_custom tools (test/functional/tools/cwl_tools/v1.0_custom/) — always available
  - galactic tools (test/functional/tools/galactic_*.cwl) — always available
  - conformance tools (v1.0/v1.1/v1.2) — only if update_cwl_conformance_tests.sh has been run
"""

import os

import yaml

import pytest

from galaxy.tool_util.parameters import input_models_for_tool_source
from galaxy.tool_util.parser import get_tool_source
from galaxy.util import galaxy_directory

TOOLS_DIR = os.path.join(galaxy_directory(), "test/functional/tools")
PARAMETERS_DIR = os.path.join(TOOLS_DIR, "parameters")
CWL_TOOLS_DIR = os.path.join(TOOLS_DIR, "cwl_tools")


def _is_workflow(path):
    """Check if a .cwl file is a Workflow (not a tool)."""
    try:
        with open(path) as f:
            doc = yaml.safe_load(f)
        if isinstance(doc, dict):
            return doc.get("class") == "Workflow"
    except Exception:
        pass
    return False


def _cwl_tools_from_dir(directory, relative_to=None):
    """Yield (rel_id, path) for all non-workflow .cwl files in directory tree."""
    if relative_to is None:
        relative_to = directory
    if not os.path.isdir(directory):
        return
    for root, _, files in os.walk(directory):
        for f in sorted(files):
            if not f.endswith(".cwl"):
                continue
            full = os.path.join(root, f)
            if _is_workflow(full):
                continue
            rel = os.path.relpath(full, relative_to)
            yield rel, full


def _parameter_cwl_tools():
    """CWL tools in test/functional/tools/parameters/cwl_*."""
    for rel, path in _cwl_tools_from_dir(PARAMETERS_DIR):
        if os.path.basename(rel).startswith("cwl_"):
            yield pytest.param(path, id=rel)


def _custom_cwl_tools():
    """CWL tools in test/functional/tools/cwl_tools/v1.0_custom/."""
    custom_dir = os.path.join(CWL_TOOLS_DIR, "v1.0_custom")
    for rel, path in _cwl_tools_from_dir(custom_dir, relative_to=CWL_TOOLS_DIR):
        yield pytest.param(path, id=rel)


def _galactic_cwl_tools():
    """Galactic CWL tools in test/functional/tools/galactic_*.cwl."""
    for rel, path in _cwl_tools_from_dir(TOOLS_DIR):
        if os.path.basename(rel).startswith("galactic_") and rel.endswith(".cwl"):
            yield pytest.param(path, id=rel)


def _conformance_cwl_tools():
    """CWL tools from downloaded conformance suites (v1.0, v1.1, v1.2).

    Only yields if update_cwl_conformance_tests.sh has been run.
    """
    for version_dir_name in ["v1.0", "v1.1", "v1.2"]:
        version_dir = os.path.join(CWL_TOOLS_DIR, version_dir_name)
        for rel, path in _cwl_tools_from_dir(version_dir, relative_to=CWL_TOOLS_DIR):
            yield pytest.param(path, id=rel)


# -- Parameter tools: must all pass --


@pytest.mark.parametrize("tool_path", list(_parameter_cwl_tools()))
def test_parameter_cwl_tool_loads(tool_path):
    """Parameter CWL tools must produce valid parameter models."""
    tool_source = get_tool_source(tool_path, macro_paths=[])
    bundle = input_models_for_tool_source(tool_source)
    assert bundle.parameters


# -- v1.0_custom tools --

CUSTOM_EXPECTED_FAILURES = {
    # non-strict CWL: has invalid 'description' field in ResourceRequirement,
    # needs non-strict schema loader (strict_cwl_validation=False)
    "v1.0_custom/md5sum_non_strict.cwl",
}


@pytest.mark.parametrize("tool_path", list(_custom_cwl_tools()))
def test_custom_cwl_tool_loads(tool_path):
    """v1.0_custom CWL tools must produce valid parameter models."""
    rel = os.path.relpath(tool_path, CWL_TOOLS_DIR)
    if rel in CUSTOM_EXPECTED_FAILURES:
        pytest.xfail(f"Known unsupported: {rel}")
    tool_source = get_tool_source(tool_path, macro_paths=[])
    bundle = input_models_for_tool_source(tool_source)
    assert bundle is not None


# -- Galactic CWL tools --

GALACTIC_EXPECTED_FAILURES: set = set()


@pytest.mark.parametrize("tool_path", list(_galactic_cwl_tools()))
def test_galactic_cwl_tool_loads(tool_path):
    """Galactic CWL tools must produce valid parameter models."""
    rel = os.path.relpath(tool_path, TOOLS_DIR)
    if rel in GALACTIC_EXPECTED_FAILURES:
        pytest.xfail(f"Known unsupported: {rel}")
    tool_source = get_tool_source(tool_path, macro_paths=[])
    bundle = input_models_for_tool_source(tool_source)
    assert bundle is not None
    assert bundle.parameters


# -- Conformance tools (optional) --


_conformance_tools_list = list(_conformance_cwl_tools())


@pytest.mark.parametrize("tool_path", _conformance_tools_list)
@pytest.mark.skipif(not _conformance_tools_list, reason="Conformance tools not downloaded")
def test_conformance_cwl_tool_loads(tool_path):
    """Conformance test CWL tools should produce valid parameter models."""
    tool_source = get_tool_source(tool_path, macro_paths=[])
    bundle = input_models_for_tool_source(tool_source)
    assert bundle is not None
