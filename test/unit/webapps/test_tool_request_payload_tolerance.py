"""Read-side tolerance for legacy ToolRequest rows whose request column
was NULL pre-migration. The 28885b317f78 backfill explicitly skips
those (defensive guard against historical anomalies), so post-migration
they keep tool_execution_state_id = NULL. Serializers must tolerate
this rather than raising, matching the pre-migration semantics where
the column itself was nullable.
"""

from galaxy import model
from galaxy.webapps.galaxy.services.base import _tool_request_payload_or_empty


def test_payload_or_empty_returns_empty_when_no_tes():
    tr = model.ToolRequest()
    tr.tool_execution_state = None

    assert _tool_request_payload_or_empty(tr) == {}


def test_payload_or_empty_returns_empty_when_tes_request_is_none():
    tr = model.ToolRequest()
    tes = model.ToolExecutionState(request=None, state="not_validated")
    tr.tool_execution_state = tes

    assert _tool_request_payload_or_empty(tr) == {}


def test_payload_or_empty_returns_dict_for_normal_case():
    tr = model.ToolRequest()
    tes = model.ToolExecutionState(request={"a": 1}, state="validated")
    tr.tool_execution_state = tes

    assert _tool_request_payload_or_empty(tr) == {"a": 1}
