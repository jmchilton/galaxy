"""Validate CWL conformance test job JSONs against CWL runtime models.

For each (tool, job) pair from conformance tests, loads the tool's parameter
models, normalizes the job JSON via cwltool's normalizeFilesDirs, then validates
against the job_runtime pydantic model.
"""

import json
import os

import yaml

import pytest

from galaxy.tool_util.cwl.job_normalization import normalize_cwl_job
from galaxy.tool_util.parameters import (
    input_models_for_tool_source,
    validate_job_runtime,
)
from galaxy.tool_util.parser import get_tool_source
from galaxy.tool_util.unittest_utils.cwl_data import conformance_tests_gen
from galaxy.util import galaxy_directory

TOOLS_DIR = os.path.join(galaxy_directory(), "test/functional/tools")
CWL_TOOLS_DIR = os.path.join(TOOLS_DIR, "cwl_tools")


def _is_workflow_or_graph(path):
    try:
        with open(path) as f:
            doc = yaml.safe_load(f)
        if isinstance(doc, dict):
            if doc.get("class") == "Workflow":
                return True
            if "$graph" in doc:
                return True
    except Exception:
        pass
    return False


def _load_job(job_path):
    with open(job_path) as f:
        if job_path.endswith(".json"):
            return json.load(f)
        else:
            return yaml.safe_load(f)


def _conformance_tool_job_pairs():
    """Yield (tool_path, job_path) from conformance tests."""
    for version in ["v1.0", "v1.1", "v1.2"]:
        version_dir = os.path.join(CWL_TOOLS_DIR, version)
        conformance_path = os.path.join(version_dir, "conformance_tests.yaml")
        if not os.path.exists(conformance_path):
            continue

        seen = set()
        for entry in conformance_tests_gen(version_dir):
            if entry.get("should_fail"):
                continue
            tags = set(entry.get("tags", []))
            if "json_schema_invalid" in tags:
                continue

            tool_rel = entry.get("tool")
            job_rel = entry.get("job")
            if not tool_rel or not job_rel:
                continue

            directory = entry.get("directory", version_dir)
            tool_path = os.path.normpath(os.path.join(directory, tool_rel))
            job_path = os.path.normpath(os.path.join(directory, job_rel))

            if not os.path.exists(tool_path) or not os.path.exists(job_path):
                continue
            if _is_workflow_or_graph(tool_path):
                continue

            pair_key = (tool_path, job_path)
            if pair_key in seen:
                continue
            seen.add(pair_key)

            test_id = f"{version}/{entry.get('id', 'unknown')}"
            yield pytest.param(tool_path, job_path, id=test_id)


_pairs_list = list(_conformance_tool_job_pairs())

EXPECTED_FAILURES: set = {
    # Union of records with enum discriminator (map1/map2/map3/map4) — each variant
    # has different optional fields, fill_defaults picks wrong variant fields.
    # Needs discriminated union fill logic.
    "v1.0/v1.0/tmap-tool.cwl",
    "v1.1/tests/tmap-tool.cwl",
    "v1.2/tests/tmap-tool.cwl",
}


@pytest.mark.parametrize("tool_path,job_path", _pairs_list)
@pytest.mark.skipif(not _pairs_list, reason="Conformance tests not downloaded")
def test_conformance_cwl_job_runtime(tool_path, job_path):
    rel_id = os.path.relpath(tool_path, CWL_TOOLS_DIR)
    if rel_id in EXPECTED_FAILURES:
        pytest.xfail(f"Known: {rel_id}")

    tool_source = get_tool_source(tool_path, macro_paths=[])
    bundle = input_models_for_tool_source(tool_source)

    job_json = _load_job(job_path)
    normalized = normalize_cwl_job(job_json, input_models=bundle)
    validate_job_runtime(bundle, normalized)
