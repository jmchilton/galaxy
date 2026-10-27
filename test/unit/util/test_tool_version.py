import pytest

from galaxy.util.tool_version import versionless_tool_id


@pytest.mark.parametrize(
    "tool_id,expected",
    [
        ("cat1", "cat1"),
        (
            "toolshed.g2.bx.psu.edu/repos/devteam/fastqc/fastqc/0.74+galaxy0",
            "toolshed.g2.bx.psu.edu/repos/devteam/fastqc/fastqc",
        ),
        ("toolshed.g2.bx.psu.edu/repos/devteam/fastqc/fastqc", "toolshed.g2.bx.psu.edu/repos/devteam/fastqc/fastqc"),
        ("localhost:9009/repos/owner/repo_name/tool_a/1.0.0", "localhost:9009/repos/owner/repo_name/tool_a"),
        ("some/local/tool", "some/local/tool"),
    ],
)
def test_versionless_tool_id(tool_id, expected):
    assert versionless_tool_id(tool_id) == expected
