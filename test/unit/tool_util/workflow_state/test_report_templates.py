"""Tests for the Jinja2 rendering module + shared templates.

Covers:
- ``_report_templates.render_report`` / ``make_markdown_renderer`` (Step 2).
- ``connection_section.md.j2`` parity vs ``format_connection_markdown`` (Step 3).
- ``_macros.md.j2`` individual macros (Step 3).
- Per-CLI tree templates vs checked-in markdown goldens (Step 4).
"""

import os

from jinja2 import Environment

from galaxy.tool_util.workflow_state._report_models import (
    ConnectionResult,
    ConnectionStepResult,
    ConnectionValidationReport,
    ResolvedOutputType,
)
from galaxy.tool_util.workflow_state._report_templates import (
    _get_env,
    make_markdown_renderer,
    render_report,
)
from galaxy.tool_util.workflow_state.export_format2 import (
    ExportTreeReport,
    WorkflowExportResult,
)
from galaxy.tool_util.workflow_state._report_models import (
    LintTreeReport,
    LintWorkflowResult,
    ValidationStepResult,
)
from galaxy.tool_util.workflow_state.precheck import SkipWorkflowReason
from galaxy.tool_util.workflow_state.to_native_stateful import (
    ToNativeTreeReport,
    WorkflowToNativeResult,
)
from galaxy.tool_util.workflow_state.validate import format_connection_markdown

GOLDENS_DIR = os.path.join(os.path.dirname(__file__), "report_markdown_goldens")


def _load_golden(name: str) -> str:
    """Load a markdown golden. Uses ``.md.golden`` suffix so prettier's
    table-aligner doesn't reformat the file (templates emit unaligned tables
    because Jinja2/Nunjucks have no shared column-pad filter)."""
    with open(os.path.join(GOLDENS_DIR, f"{name}.md.golden")) as fh:
        return fh.read()


# -- rendering module smoke (Step 2) -----------------------------------------


def test_env_is_singleton() -> None:
    assert _get_env() is _get_env()


def test_env_config_matches_plan() -> None:
    env: Environment = _get_env()
    assert env.trim_blocks is True
    assert env.lstrip_blocks is True
    assert env.keep_trailing_newline is False
    # No custom filters / globals — Nunjucks parity constraint from the plan.
    default_filters = set(Environment().filters)
    default_globals = set(Environment().globals)
    assert set(env.filters) == default_filters
    assert set(env.globals) == default_globals


# -- connection_section.md.j2 parity (Step 3) --------------------------------


def _connection_report_with_details() -> ConnectionValidationReport:
    return ConnectionValidationReport(
        valid=False,
        step_results=[
            ConnectionStepResult(
                step="1",
                tool_id="cat1",
                version="1.0.0",
                connections=[
                    ConnectionResult(
                        source_step="0",
                        source_output="output",
                        target_step="1",
                        target_input="input",
                        status="ok",
                    ),
                    ConnectionResult(
                        source_step="0",
                        source_output="output",
                        target_step="1",
                        target_input="other",
                        status="invalid",
                        errors=["type mismatch: data vs collection"],
                    ),
                ],
                resolved_outputs=[ResolvedOutputType(name="output")],
            ),
            ConnectionStepResult(
                step="2",
                tool_id=None,
                connections=[],
                errors=["step-level: tool not found"],
            ),
        ],
        summary={"ok": 1, "invalid": 1, "skip": 0},
    )


def _empty_connection_report() -> ConnectionValidationReport:
    return ConnectionValidationReport(valid=True, step_results=[], summary={"ok": 0, "invalid": 0, "skip": 0})


def test_connection_section_parity_with_details() -> None:
    report = _connection_report_with_details()
    expected = format_connection_markdown(report).rstrip() + "\n"
    actual = render_report("connection_section.md.j2", report)
    assert actual == expected, f"\n--- expected ---\n{expected}\n--- actual ---\n{actual}"


def test_connection_section_parity_empty() -> None:
    report = _empty_connection_report()
    expected = format_connection_markdown(report).rstrip() + "\n"
    actual = render_report("connection_section.md.j2", report)
    assert actual == expected, f"\n--- expected ---\n{expected}\n--- actual ---\n{actual}"


def test_make_markdown_renderer_signature() -> None:
    renderer = make_markdown_renderer("connection_section.md.j2")
    out = renderer(_empty_connection_report())
    assert "Connection Validation" in out


# -- _macros.md.j2 individual macros (Step 3) --------------------------------

_MACRO_TEST_TEMPLATE = """\
{% import "_macros.md.j2" as m -%}
{{ m.status_badge("PASS") }}
---
{{ m.kv_summary({"ok": 3, "fail": 1, "skip": 0}) }}
---
{{ m.failure_bullet({"workflow": "catA/wf.ga", "step": "2", "tool_id": "Grep1", "message": "boom"}) }}
---
{{ m.workflow_state_cells({"skipped_reason": "legacy_encoding", "error": None, "summary": None, "results": []}) }}
---
{{ m.workflow_state_cells({"skipped_reason": None, "error": "parse failed", "summary": None, "results": []}) }}
---
{{ m.workflow_state_cells({"skipped_reason": None, "error": None, "summary": {"ok": 3, "fail": 1, "skip_tool_not_found": 0}, "results": [1, 2, 3, 4]}) }}
"""


def test_macros_render_all_branches() -> None:
    env = _get_env()
    template = env.from_string(_MACRO_TEST_TEMPLATE)
    out = template.render()
    sections = [s.strip() for s in out.split("---")]
    assert sections[0] == "**Status:** PASS"
    assert sections[1] == "ok: 3, fail: 1, skip: 0"
    assert sections[2] == "- **catA/wf.ga** Step 2 (Grep1): boom"
    assert sections[3] == "- | - | - | - | SKIPPED: legacy_encoding"
    assert sections[4] == "- | - | - | - | ERROR: parse failed"
    assert sections[5] == "4 | 3 | 1 | 0 |"


# -- export_tree.md.j2 golden (Step 4) ---------------------------------------


def _export_tree_fixture() -> ExportTreeReport:
    return ExportTreeReport(
        root="/tmp/workflows",
        output_dir="/tmp/out",
        results=[
            WorkflowExportResult(
                path="/tmp/workflows/catA/wf_ok.ga",
                relative_path="catA/wf_ok.ga",
                category="catA",
                ok=True,
                steps_converted=4,
                steps_fallback=0,
            ),
            WorkflowExportResult(
                path="/tmp/workflows/catA/wf_partial.ga",
                relative_path="catA/wf_partial.ga",
                category="catA",
                ok=False,
                steps_converted=3,
                steps_fallback=2,
            ),
            WorkflowExportResult(
                path="/tmp/workflows/catB/wf_err.ga",
                relative_path="catB/wf_err.ga",
                category="catB",
                error="export failed",
            ),
            WorkflowExportResult(
                path="/tmp/workflows/catB/wf_skip.ga",
                relative_path="catB/wf_skip.ga",
                category="catB",
                skipped_reason="legacy encoding",
            ),
        ],
    )


def test_export_tree_matches_golden() -> None:
    expected = _load_golden("export_tree").rstrip() + "\n"
    actual = render_report("export_tree.md.j2", _export_tree_fixture()).rstrip() + "\n"
    assert actual == expected, f"\n--- expected ---\n{expected}\n--- actual ---\n{actual}"


# -- to_native_tree.md.j2 golden (Step 4) ------------------------------------


def _to_native_tree_fixture() -> ToNativeTreeReport:
    return ToNativeTreeReport(
        root="/tmp/workflows",
        output_dir="/tmp/out",
        results=[
            WorkflowToNativeResult(
                path="/tmp/workflows/catA/wf_ok.ga",
                relative_path="catA/wf_ok.ga",
                category="catA",
                ok=True,
                steps_encoded=4,
                steps_fallback=0,
            ),
            WorkflowToNativeResult(
                path="/tmp/workflows/catA/wf_partial.ga",
                relative_path="catA/wf_partial.ga",
                category="catA",
                ok=False,
                steps_encoded=3,
                steps_fallback=2,
            ),
            WorkflowToNativeResult(
                path="/tmp/workflows/catB/wf_err.ga",
                relative_path="catB/wf_err.ga",
                category="catB",
                error="conversion failed",
            ),
            WorkflowToNativeResult(
                path="/tmp/workflows/catB/wf_skip.ga",
                relative_path="catB/wf_skip.ga",
                category="catB",
                skipped_reason="native format (not format2)",
            ),
        ],
    )


def test_to_native_tree_matches_golden() -> None:
    expected = _load_golden("to_native_tree").rstrip() + "\n"
    actual = render_report("to_native_tree.md.j2", _to_native_tree_fixture()).rstrip() + "\n"
    assert actual == expected, f"\n--- expected ---\n{expected}\n--- actual ---\n{actual}"


# -- lint_tree.md.j2 golden (Step 4) -----------------------------------------


def _lint_tree_fixture() -> LintTreeReport:
    def step(i: int, status: str) -> ValidationStepResult:
        return ValidationStepResult(step=str(i), tool_id=f"tool_{i}", status=status)

    return LintTreeReport(
        root="/tmp/workflows",
        results=[
            LintWorkflowResult(
                path="/tmp/workflows/catA/wf_ok.ga",
                relative_path="catA/wf_ok.ga",
                category="catA",
                lint_errors=0,
                lint_warnings=1,
                step_results=[step(1, "ok"), step(2, "ok"), step(3, "ok")],
            ),
            LintWorkflowResult(
                path="/tmp/workflows/catA/wf_fail.ga",
                relative_path="catA/wf_fail.ga",
                category="catA",
                lint_errors=2,
                lint_warnings=0,
                step_results=[step(1, "ok"), step(2, "fail"), step(3, "fail")],
            ),
            LintWorkflowResult(
                path="/tmp/workflows/catB/wf_err.ga",
                relative_path="catB/wf_err.ga",
                category="catB",
                error="parse failed",
            ),
            LintWorkflowResult(
                path="/tmp/workflows/catB/wf_skip.ga",
                relative_path="catB/wf_skip.ga",
                category="catB",
                skipped_reason=SkipWorkflowReason.LEGACY_ENCODING,
            ),
        ],
    )


def test_lint_tree_matches_golden() -> None:
    expected = _load_golden("lint_tree").rstrip() + "\n"
    actual = render_report("lint_tree.md.j2", _lint_tree_fixture()).rstrip() + "\n"
    assert actual == expected, f"\n--- expected ---\n{expected}\n--- actual ---\n{actual}"
