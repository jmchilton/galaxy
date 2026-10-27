import pytest
import yaml

from galaxy.util.resources import resource_string
from galaxy.util.tool_version import versionless_tool_id

# Shared with the client's versionlessToolId tests.
SPEC = yaml.safe_load(resource_string("galaxy.util", "versionless_tool_id_spec.yml"))


@pytest.mark.parametrize("case", SPEC, ids=[case["tool_id"] for case in SPEC])
def test_versionless_tool_id(case):
    assert versionless_tool_id(case["tool_id"]) == case["versionless"], case["doc"]
