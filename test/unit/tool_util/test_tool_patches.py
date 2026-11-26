"""Tests for galaxy.tool_util.patches."""

import struct
from pathlib import Path
from typing import Any

import pytest
import yaml
from pydantic import ValidationError

from galaxy.tool_util.parser import get_tool_source
from galaxy.tool_util.parser.xml import XmlToolSource
from galaxy.tool_util.patches.engine import (
    ALREADY_APPLIED,
    APPLIED,
    evaluate_unit,
    MISMATCH,
    UnitResult,
)
from galaxy.tool_util.patches.hg import read_working_parent
from galaxy.tool_util.patches.keys import (
    decode_segment,
    encode_segment,
    is_canonical_segment,
    patch_key,
)
from galaxy.tool_util.patches.model import (
    PatchFile,
    PatchOp,
)

UPSTREAM = {"repo": "galaxyproject/tools-iuc", "pr": 1, "merge_commit": "0123456789abcdef0123456789abcdef01234567"}
GALAXY_CHANGE = [{"repo": "galaxyproject/galaxy", "pr": 2}]
DOC = "Jobs whose label contained a space now run with it quoted."

PROBE_TOOL = """<tool id="patch_probe" name="Patch Probe" version="1.0+galaxy0" profile="23.0">
    <command><![CDATA[
cat '$input1' > '$output1' &&
echo $label >> '$output1'
    ]]></command>
    <inputs>
        <param name="input1" type="data" format="txt"/>
        <param name="label" type="text" value="x">
            <sanitizer>
                <valid initial="string.ascii_letters"/>
            </sanitizer>
        </param>
        <param name="a" type="integer" value="1"/>
        <param name="b" type="integer" value="2"/>
        <param name="c" type="integer" value="3"/>
    </inputs>
    <outputs>
        <data name="output1" format="txt"/>
    </outputs>
    <help>Old help.</help>
</tool>
"""


def text_op(old: str, new: str, path: str = "command", occurrences: Any = 1, **meta: Any) -> dict[str, Any]:
    return {"replace_text": {"path": path, "old": old, "new": new, "occurrences": occurrences}, **meta}


QUOTE_LABEL = text_op("echo $label >>", "echo '$label' >>")


def security_doc(*ops: dict[str, Any], **fields: Any) -> dict[str, Any]:
    doc: dict[str, Any] = {
        "format_version": 1,
        "kind": "security",
        "upstream": [UPSTREAM],
        "reproducibility": "special_inputs",
        "reproducibility_doc": DOC,
        "ops": list(ops),
    }
    doc.update(fields)
    return {k: v for k, v in doc.items() if v is not None}


def compat_doc(*ops: dict[str, Any], **fields: Any) -> dict[str, Any]:
    doc: dict[str, Any] = {
        "format_version": 1,
        "kind": "compat",
        "needed_from": "26.1",
        "galaxy_change": GALAXY_CHANGE,
        "upstream": [],
        "reproducibility": "identical",
        "reproducibility_reason": "restores what older Galaxy releases did",
        "reproducibility_doc": "No job behaves differently.",
        "ops": list(ops),
    }
    doc.update(fields)
    return {k: v for k, v in doc.items() if v is not None}


ADVISORY = {"fixed_in": "1.0+galaxy1", "vulnerable": True, "action": "upgrade", "code": "context_drift", "reason": "r"}


def write_tool(path: Path, content: str = PROBE_TOOL) -> XmlToolSource:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)
    tool_source = get_tool_source(config_file=str(path))
    assert isinstance(tool_source, XmlToolSource)
    return tool_source


def run(tool_source: XmlToolSource, *ops: dict[str, Any]) -> UnitResult:
    return evaluate_unit(tool_source.xml_tree, [PatchOp.model_validate(op).body for op in ops])


@pytest.fixture
def probe(tmp_path: Path) -> XmlToolSource:
    return write_tool(tmp_path / "tools" / "probe.xml")


# --- model / load-time lint ---


@pytest.mark.parametrize(
    "doc",
    [
        pytest.param(security_doc({"set_attribute": {"path": "command", "name": "x", "value": "y"}}), id="unknown_op"),
        pytest.param(security_doc(QUOTE_LABEL, {"kind": "security"}), id="op_without_op_type"),
        pytest.param(
            security_doc(
                {**QUOTE_LABEL, "replace_element": {"path": "x", "old": "<x/>", "new": "<y/>", "occurrences": 1}}
            ),
            id="two_op_types",
        ),
        *[
            pytest.param(security_doc(text_op("a", "b", path=f"./@{attr}")), id=f"root_{attr}")
            for attr in ("id", "version", "profile", "tool_type")
        ],
        pytest.param(
            security_doc({"replace_element": {"path": ".", "old": "<tool/>", "new": "<tool/>", "occurrences": 1}}),
            id="replace_root",
        ),
        pytest.param(
            security_doc({"remove_element": {"path": ".", "old": "<tool/>", "occurrences": 1}}), id="remove_root"
        ),
        pytest.param(
            security_doc({"replace_element": {"path": "help", "old": "<help/>", "new": "<tool/>", "occurrences": 1}}),
            id="tool_fragment",
        ),
        *[
            pytest.param(security_doc(text_op("a", "b", occurrences=v)), id=f"occurrences_{v!r}")
            for v in (True, 1.0, "1", 0)
        ],
        pytest.param(security_doc(text_op("a", "a")), id="old_equals_new"),
        pytest.param(security_doc(text_op("", "b")), id="empty_old"),
        pytest.param(security_doc(text_op("a", "")), id="empty_new_text"),
        pytest.param(security_doc(text_op("a", "b", path="command[")), id="bad_selector"),
        pytest.param(
            security_doc({"add_element": {"parent": ".", "new": "<stdio/>", "position": "middle", "occurrences": 1}}),
            id="bad_position",
        ),
        pytest.param(
            security_doc({"replace_element": {"path": "help", "old": "<help>", "new": "<help/>", "occurrences": 1}}),
            id="bad_fragment",
        ),
        pytest.param(security_doc(QUOTE_LABEL, reproducibility_doc=None), id="missing_doc"),
        pytest.param(security_doc(QUOTE_LABEL, reproducibility_doc="  "), id="blank_doc"),
        pytest.param(compat_doc(QUOTE_LABEL, reproducibility_doc=None), id="missing_doc_at_identical"),
        pytest.param(security_doc(QUOTE_LABEL, reproducibility=None), id="missing_level"),
        pytest.param(security_doc(QUOTE_LABEL, reproducibility="rejects_inputs"), id="lowered_without_reason"),
        pytest.param(
            security_doc(QUOTE_LABEL, reproducibility="rejects_inputs", reproducibility_reason=" "), id="blank_reason"
        ),
        pytest.param(
            security_doc(
                {
                    "replace_element": {
                        "path": "requirements/requirement",
                        "old": '<requirement type="package">a</requirement>',
                        "new": '<requirement type="package" version="2">a</requirement>',
                        "occurrences": 1,
                    }
                },
                reproducibility="all_inputs",
            ),
            id="requirements_op_without_flag",
        ),
        pytest.param(security_doc(QUOTE_LABEL, changes_requirements=True), id="flag_without_requirements_op"),
        pytest.param({k: v for k, v in security_doc(QUOTE_LABEL).items() if k != "kind"}, id="missing_kind"),
        pytest.param(security_doc(QUOTE_LABEL, kind="other"), id="unknown_kind"),
        pytest.param(security_doc(QUOTE_LABEL, format_version=2), id="format_version"),
        pytest.param(security_doc({**QUOTE_LABEL, "kind": "compat"}), id="op_kind_differs_from_file"),
        pytest.param(
            security_doc(
                {**QUOTE_LABEL, "kind": "security"}, kind="mixed", upstream=[{**UPSTREAM, "kind": "security"}]
            ),
            id="mixed_without_compat",
        ),
        pytest.param(
            security_doc(
                {**QUOTE_LABEL, "kind": "security"},
                {**text_op("cat", "cat -"), "kind": "compat", "needed_from": "26.1"},
                kind="mixed",
                galaxy_change=GALAXY_CHANGE,
                upstream=[UPSTREAM],
            ),
            id="mixed_upstream_without_kind",
        ),
        pytest.param(
            security_doc(
                QUOTE_LABEL,
                {**text_op("cat", "cat -"), "kind": "compat", "needed_from": "26.1"},
                kind="mixed",
                galaxy_change=GALAXY_CHANGE,
                upstream=[{**UPSTREAM, "kind": "security"}],
            ),
            id="mixed_op_without_kind",
        ),
        pytest.param(compat_doc(QUOTE_LABEL, needed_from=None), id="compat_op_without_needed_from"),
        pytest.param(compat_doc(QUOTE_LABEL, galaxy_change=None), id="compat_without_galaxy_change"),
        pytest.param(compat_doc(QUOTE_LABEL, reproducibility="special_inputs"), id="compat_not_identical"),
        pytest.param(security_doc({**QUOTE_LABEL, "needed_from": "26.1"}), id="security_op_needed_from"),
        pytest.param(security_doc(QUOTE_LABEL, needed_from="26.1"), id="security_file_needed_from"),
        pytest.param(security_doc(QUOTE_LABEL, galaxy_change=GALAXY_CHANGE), id="security_file_galaxy_change"),
        pytest.param(security_doc(QUOTE_LABEL, upstream=[]), id="security_ops_without_upstream"),
        pytest.param(compat_doc(QUOTE_LABEL, needed_from=26.1), id="needed_from_float"),
        pytest.param(compat_doc(QUOTE_LABEL, needed_from="26.1.2"), id="needed_from_point_release"),
        pytest.param(security_doc(ops=None), id="neither_ops_nor_advisory"),
        pytest.param(security_doc(ops=[]), id="empty_ops"),
        pytest.param(
            security_doc(ops=None, reproducibility=None, reproducibility_doc=None, advisory=ADVISORY, fixes=[]),
            id="advisory_only_with_ops_field",
        ),
        pytest.param(
            security_doc(
                ops=None,
                reproducibility=None,
                reproducibility_doc=None,
                advisory=ADVISORY,
                changes_requirements=False,
            ),
            id="advisory_only_with_explicit_false_flag",
        ),
        pytest.param(
            security_doc(
                ops=None,
                reproducibility=None,
                reproducibility_doc=None,
                advisory={**ADVISORY, "action": "enable_policy"},
            ),
            id="advisory_enable_policy",
        ),
        pytest.param(
            security_doc(ops=None, reproducibility=None, reproducibility_doc=None, advisory=ADVISORY, upstream=[]),
            id="security_advisory_without_upstream",
        ),
        pytest.param(security_doc(QUOTE_LABEL, surprise=1), id="unknown_field"),
    ],
)
def test_invalid_patch_files_are_rejected(doc: dict[str, Any]) -> None:
    with pytest.raises(ValidationError):
        PatchFile.model_validate(doc)


def test_unquoted_needed_from_in_yaml_is_rejected() -> None:
    doc = yaml.safe_load(yaml.safe_dump(compat_doc(QUOTE_LABEL)).replace("'26.1'", "26.1"))
    assert doc["needed_from"] == 26.1
    with pytest.raises(ValidationError, match="needed_from"):
        PatchFile.model_validate(doc)


@pytest.mark.parametrize(
    "doc",
    [
        pytest.param(
            security_doc(
                text_op("Old help.", "New help.", path="help"),
                reproducibility="identical",
                reproducibility_reason="help text only",
            ),
            id="help",
        ),
        pytest.param(
            security_doc(
                {
                    "replace_element": {
                        "path": "requirements/requirement",
                        "old": '<requirement type="package">a</requirement>',
                        "new": '<requirement type="package" version="2">a</requirement>',
                        "occurrences": 1,
                    }
                },
                reproducibility="all_inputs",
                changes_requirements=True,
            ),
            id="requirements",
        ),
        pytest.param(
            security_doc(
                {
                    "add_element": {
                        "parent": ".//param[@name='label']",
                        "new": '<validator type="regex">[a-z]+</validator>',
                        "occurrences": 1,
                    }
                },
                reproducibility="rejects_inputs",
            ),
            id="validator_proposes_rejects_inputs",
        ),
        pytest.param(security_doc(QUOTE_LABEL, advisory={**ADVISORY, "code": "partial_fix"}), id="ops_and_advisory"),
        pytest.param(
            security_doc(QUOTE_LABEL, reproducibility="rejects_inputs", reproducibility_reason="reviewed"),
            id="lowered_with_reason",
        ),
        pytest.param(
            security_doc(
                {**QUOTE_LABEL, "kind": "security"},
                {**text_op("cat", "cat -"), "kind": "compat"},
                kind="mixed",
                needed_from="26.1",
                galaxy_change=GALAXY_CHANGE,
                upstream=[{**UPSTREAM, "kind": "security"}],
            ),
            id="mixed",
        ),
        pytest.param(security_doc(QUOTE_LABEL), id="security_builder"),
        pytest.param(compat_doc(QUOTE_LABEL), id="compat_builder"),
        pytest.param(
            compat_doc(
                QUOTE_LABEL, advisory={**ADVISORY, "kind": "security"}, upstream=[{**UPSTREAM, "kind": "security"}]
            ),
            id="compat_with_security_advisory",
        ),
        pytest.param(
            compat_doc(
                {
                    "remove_element": {
                        "path": "tests/test",
                        "old": '<test><param name="a" value="1"/></test>',
                        "occurrences": 1,
                    }
                }
            ),
            id="remove_element",
        ),
    ],
)
def test_valid_patch_files_load(doc: dict[str, Any]) -> None:
    PatchFile.model_validate(doc)


# --- engine ---


def test_pre_applies(probe: XmlToolSource) -> None:
    result = run(probe, QUOTE_LABEL)
    assert result.state == APPLIED
    assert result.tree is not None
    assert "echo '$label' >>" in result.tree.getroot().findtext("command")
    assert "echo $label >>" in probe.xml_tree.getroot().findtext("command")


def test_post_is_already_applied(tmp_path: Path) -> None:
    fixed = write_tool(tmp_path / "fixed.xml", PROBE_TOOL.replace("echo $label", "echo '$label'"))
    assert run(fixed, QUOTE_LABEL).state == ALREADY_APPLIED


@pytest.mark.parametrize(
    "ops",
    [
        pytest.param([text_op("echo $label |", "echo '$label' |")], id="neither"),
        pytest.param([QUOTE_LABEL, text_op("cat '$input1'", "cat -- '$input1'", occurrences=2)], id="wrong_count"),
        # the second op's post-image is already present
        pytest.param([QUOTE_LABEL, text_op("cat -- '$input1'", "cat '$input1'")], id="pre_post_mix"),
    ],
)
def test_neither_or_mix_is_mismatch(probe: XmlToolSource, ops: list[dict[str, Any]]) -> None:
    result = run(probe, *ops)
    assert result.state == MISMATCH
    assert result.tree is None


def test_fixed_content_differing_from_new_is_mismatch(tmp_path: Path) -> None:
    fixed_differently = write_tool(tmp_path / "other.xml", PROBE_TOOL.replace("echo $label", 'echo "$label"'))
    assert run(fixed_differently, QUOTE_LABEL).state == MISMATCH


def test_insertion_with_old_inside_new_is_already_applied_after_apply(probe: XmlToolSource) -> None:
    insert = text_op("cat '$input1'", "#set $x = 1\ncat '$input1'")
    applied = run(probe, insert)
    assert applied.state == APPLIED and applied.tree is not None
    assert evaluate_unit(applied.tree, [PatchOp.model_validate(insert).body]).state == ALREADY_APPLIED


ROUND_TRIP_OPS = {
    "replace_text": QUOTE_LABEL,
    "replace_element": {
        "replace_element": {
            "path": ".//param[@name='label']/sanitizer",
            "old": '<sanitizer><valid initial="string.ascii_letters"/></sanitizer>',
            "new": '<sanitizer invalid_char=""><valid initial="string.ascii_letters"/></sanitizer>',
            "occurrences": 1,
        }
    },
    "add_element": {
        "add_element": {
            "parent": ".//param[@type='integer']",
            "new": '<validator type="in_range" min="0"/>',
            "position": "first",
            "occurrences": 3,
        }
    },
    "remove_element": {
        "remove_element": {
            "path": ".//param[@name='label']/sanitizer/valid",
            "old": '<valid initial="string.ascii_letters"/>',
            "occurrences": 1,
        }
    },
}


@pytest.mark.parametrize("op", ROUND_TRIP_OPS.values(), ids=ROUND_TRIP_OPS.keys())
def test_round_trip(probe: XmlToolSource, op: dict[str, Any]) -> None:
    first = run(probe, op)
    assert first.state == APPLIED, first.detail
    assert first.tree is not None
    body = PatchOp.model_validate(op).body
    assert evaluate_unit(first.tree, [body]).state == ALREADY_APPLIED


def test_add_element_inserts_into_every_parent(probe: XmlToolSource) -> None:
    result = run(probe, ROUND_TRIP_OPS["add_element"])
    assert result.tree is not None
    params = result.tree.getroot().findall(".//param[@type='integer']")
    assert [p[0].tag for p in params] == ["validator"] * 3


@pytest.mark.parametrize("occurrences,state", [(2, MISMATCH), (3, APPLIED), (4, MISMATCH)])
def test_add_element_needs_exact_parent_count(probe: XmlToolSource, occurrences: int, state: str) -> None:
    op = {"add_element": {**ROUND_TRIP_OPS["add_element"]["add_element"], "occurrences": occurrences}}
    assert run(probe, op).state == state


@pytest.mark.parametrize("existing,state", [(False, APPLIED), (True, MISMATCH)])
def test_add_element_refuses_second_singleton(tmp_path: Path, existing: bool, state: str) -> None:
    content = PROBE_TOOL
    if existing:
        content = content.replace(
            "<inputs>", '<configfiles><configfile name="a">x</configfile></configfiles>\n    <inputs>'
        )
    tool_source = write_tool(tmp_path / "configfiles.xml", content)
    op = {
        "add_element": {
            "parent": ".",
            "new": '<configfiles><configfile name="name_file">$label</configfile></configfiles>',
            "position": "before:inputs",
            "occurrences": 1,
        }
    }
    assert run(tool_source, op).state == state


def test_atomic_failure_leaves_source_unchanged(probe: XmlToolSource) -> None:
    before = probe.to_string()
    # both anchors are present, but the first op consumes the second's anchor
    result = run(probe, QUOTE_LABEL, text_op("$label >>", "${label} >>"))
    assert result.state == MISMATCH
    assert result.tree is None
    assert "no longer" in (result.detail or "")
    assert probe.to_string() == before


def test_selector_invariance_failure_is_mismatch(probe: XmlToolSource) -> None:
    ops = [
        {
            "add_element": {
                "parent": ".//param[@name='label']/sanitizer",
                "new": '<mapping initial="none"/>',
                "occurrences": 1,
            }
        },
        {
            "replace_element": {
                "path": ".//param[@name='label']/sanitizer/*",
                "old": '<valid initial="string.ascii_letters"/>',
                "new": '<valid initial="string.digits"/>',
                "occurrences": 1,
            }
        },
    ]
    result = run(probe, *ops)
    assert result.state == MISMATCH
    assert "selector" in (result.detail or "")


def test_parameter_model_change_is_mismatch(probe: XmlToolSource) -> None:
    op = {
        "replace_element": {
            "path": ".//param[@name='a']",
            "old": '<param name="a" type="integer" value="1"/>',
            "new": '<param name="a" type="text" value="1"/>',
            "occurrences": 1,
        }
    }
    result = run(probe, op)
    assert result.state == MISMATCH
    assert result.detail == "parameter model changed"


# --- keys ---


@pytest.mark.parametrize(
    "raw,encoded",
    [
        ("1.4.5+Galaxy2", "1.4.5+!galaxy2"),
        ("EMBOSS: sirna89", "!e!m!b!o!s!s%3A%20sirna89"),
        ("plain_id-1.0", "plain_id-1.0"),
        ("a!b%c/d", "a%21b%25c%2Fd"),
        ("é", "%C3%A9"),
    ],
)
def test_segment_encoding(raw: str, encoded: str) -> None:
    assert encode_segment(raw) == encoded
    assert decode_segment(encoded) == raw
    assert is_canonical_segment(encoded)


@pytest.mark.parametrize("segment", ["Abc", "%3a", "!E", "%41", "a b", "", ".", "..", "%2", "!"])
def test_non_canonical_segments(segment: str) -> None:
    assert not is_canonical_segment(segment)


def test_patch_key_from_shed_guid_drops_host(probe: XmlToolSource) -> None:
    guid = "toolshed.example.org/repos/Owner1/repo_a/patch_probe/1.0+galaxy7"
    assert patch_key(probe, guid) == ("Owner1", "repo_a", "patch_probe", "1.0+galaxy7")


@pytest.mark.parametrize("guid", [None, "patch_probe"])
def test_patch_key_for_non_shed_tools(probe: XmlToolSource, guid: str | None) -> None:
    assert patch_key(probe, guid) == ("_local", "patch_probe", "1.0+galaxy0")


def test_malformed_shed_guid_has_no_key(probe: XmlToolSource) -> None:
    assert patch_key(probe, "toolshed.example.org/repos/owner/repo/patch_probe") is None


# --- dirstate ---

NODE = bytes(range(20))


def _hg_dir(tmp_path: Path, dirstate: bytes, requires: str = "revlogv1\nstore\n") -> Path:
    repo = tmp_path / "repo"
    (repo / ".hg").mkdir(parents=True)
    (repo / ".hg" / "requires").write_text(requires)
    (repo / ".hg" / "dirstate").write_bytes(dirstate)
    return repo


def test_dirstate_v1(tmp_path: Path) -> None:
    repo = _hg_dir(tmp_path, NODE + b"\0" * 20 + b"n" + b"\0" * 16)
    assert read_working_parent(str(repo)) == NODE.hex()


def test_dirstate_v2_docket(tmp_path: Path) -> None:
    docket = struct.pack(">12s32s32s44sLB", b"dirstate-v2\n", NODE, b"", b"\0" * 44, 0, 4) + b"abcd"
    repo = _hg_dir(tmp_path, docket, requires="dirstate-v2\nrevlogv1\nstore\n")
    assert read_working_parent(str(repo)) == NODE.hex()


@pytest.mark.parametrize(
    "dirstate,requires",
    [
        pytest.param(b"", "store\n", id="empty"),
        pytest.param(b"\0" * 40, "store\n", id="null_parent"),
        pytest.param(b"short", "store\n", id="truncated"),
        pytest.param(NODE + b"\0" * 20, "dirstate-v2\n", id="v2_required_without_marker"),
    ],
)
def test_unreadable_dirstate(tmp_path: Path, dirstate: bytes, requires: str) -> None:
    assert read_working_parent(str(_hg_dir(tmp_path, dirstate, requires))) is None


def test_missing_dirstate(tmp_path: Path) -> None:
    assert read_working_parent(str(tmp_path)) is None
