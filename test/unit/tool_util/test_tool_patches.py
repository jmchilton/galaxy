"""Tests for galaxy.tool_util.patches."""

import hashlib
import logging
import os
import shutil
import struct
import subprocess
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest
import yaml
from pydantic import ValidationError

from galaxy.tool_util.parser import get_tool_source
from galaxy.tool_util.parser.interface import ToolSource
from galaxy.tool_util.parser.xml import XmlToolSource
from galaxy.tool_util.patches import (
    collection as patch_collection,
    load_tool_patch_database,
    PatchState,
    ToolPatchDatabase,
)
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
    key_from_ids,
    patch_key,
)
from galaxy.tool_util.patches.model import (
    PatchFile,
    PatchOp,
)
from galaxy.tool_util.unittest_utils import functional_test_tool_path
from galaxy.tool_util.unittest_utils.tool_patches import (
    UPSTREAM,
    write_collection,
)
from galaxy.util.template import fill_template

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
        "reproducibility": "unusual_inputs",
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


def command_text(command: str | None) -> str:
    assert command is not None
    return command


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
                reproducibility="ordinary_inputs",
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
        pytest.param(compat_doc(QUOTE_LABEL, reproducibility="unusual_inputs"), id="compat_not_identical"),
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
                reproducibility="ordinary_inputs",
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
    assert "echo '$label' >>" in command_text(result.tree.getroot().findtext("command"))
    assert "echo $label >>" in command_text(probe.xml_tree.getroot().findtext("command"))


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


# --- collections and database ---

LOCAL_PROBE = "_local/patch_probe/1.0+galaxy0.yml"
LOCAL_KEY = ("_local", "patch_probe", "1.0+galaxy0")
SHED_GUID = "toolshed.example.org/repos/owner1/repo_a/patch_probe/1.0+galaxy0"
SHED_PROBE = "owner1/repo_a/patch_probe/1.0+galaxy0"
SHED_KEY = ("owner1", "repo_a", "patch_probe", "1.0+galaxy0")
NODE_HEX = NODE.hex()
OVERRIDE_REL = f"{SHED_PROBE}/@{NODE_HEX[:12]}.yml"
OVERRIDE_OP = text_op("cat '$input1' >", "cat -- '$input1' >")
DIRSTATE_V1 = NODE + b"\0" * 20
DIRSTATE_V2 = struct.pack(">12s32s32s44sLB", b"dirstate-v2\n", NODE, b"", b"\0" * 44, 0, 4) + b"abcd"
ADVISORY_ONLY = {"ops": None, "reproducibility": None, "reproducibility_doc": None}
CODES = {"partial_fix": {"level": "must_fix", "actions": ["upgrade"], "message": "Upgrade to {fixed_in} or later."}}
REQUIREMENT_TOOL = PROBE_TOOL.replace(
    "<inputs>",
    '<requirements><requirement type="package" version="1.0">probe</requirement></requirements>\n    <inputs>',
)
REQUIREMENT_OP = {
    "replace_element": {
        "path": "requirements/requirement",
        "old": '<requirement type="package" version="1.0">probe</requirement>',
        "new": '<requirement type="package" version="1.1">probe</requirement>',
        "occurrences": 1,
    }
}


def load_db(*roots: Path, **kwds: Any) -> ToolPatchDatabase:
    return load_tool_patch_database([str(r) for r in roots], **kwds)


def patch_states(tool_source: ToolSource) -> list[PatchState]:
    assert tool_source.patch_state is not None
    return tool_source.patch_state.states


def states_of(tool_source: ToolSource) -> list[str]:
    return [s.state for s in patch_states(tool_source)]


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def shed_repo_tool(tmp_path: Path, dirstate: bytes = DIRSTATE_V1, requires: str = "store\n") -> XmlToolSource:
    return write_tool(_hg_dir(tmp_path, dirstate, requires) / "tools" / "probe.xml")


def test_miss_returns_same_object(tmp_path: Path, probe: XmlToolSource) -> None:
    db = load_db(write_collection(tmp_path / "c", {"_local/other_tool/1.0.yml": security_doc(QUOTE_LABEL)}))
    assert db.apply_patches(probe) is probe
    assert probe.patch_state is None
    assert db.digest_for(LOCAL_KEY) is None


@pytest.mark.parametrize(
    "rel,guid",
    [(LOCAL_PROBE, SHED_GUID), (f"{SHED_PROBE}.yml", None), (f"{SHED_PROBE}.yml", "patch_probe")],
    ids=["shed_guid_vs_local_key", "no_guid_vs_shed_key", "bare_id_vs_shed_key"],
)
def test_shed_and_local_keys_never_cross(tmp_path: Path, probe: XmlToolSource, rel: str, guid: str | None) -> None:
    db = load_db(write_collection(tmp_path / "c", {rel: security_doc(QUOTE_LABEL)}))
    assert db.apply_patches(probe, guid=guid) is probe
    assert probe.patch_state is None


@pytest.mark.parametrize(
    "rel,guid,key", [(LOCAL_PROBE, None, LOCAL_KEY), (f"{SHED_PROBE}.yml", SHED_GUID, SHED_KEY)], ids=["local", "shed"]
)
def test_applied_patch_rebuilds_tool_source(
    tmp_path: Path, probe: XmlToolSource, rel: str, guid: str | None, key: tuple[str, ...]
) -> None:
    root = write_collection(tmp_path / "c", {rel: security_doc(QUOTE_LABEL)})
    db = load_db(root)
    before = probe.to_string()

    patched = db.apply_patches(probe, guid=guid)

    assert patched is not probe
    assert "echo '$label' >>" in command_text(patched.parse_command())
    assert "echo '$label'" in patched.to_string()
    assert probe.to_string() == before
    assert probe.patch_state is None
    assert (patched.source_path, patched.macro_paths) == (probe.source_path, probe.macro_paths)
    info = patched.patch_state
    assert info is not None and info.digest == db.digest_for(key)
    (state,) = info.states
    assert (state.state, state.kind, state.key, state.path) == ("applied", "security", "/".join(key), f"patches/{rel}")
    assert state.digest == hashlib.sha256((root / "patches" / rel).read_bytes()).hexdigest()
    assert (state.collection.name, state.collection.version) == ("test-patches", "2026.11.25")
    assert (state.reproducibility, state.reproducibility_doc, state.upstream[0].pr) == ("unusual_inputs", DOC, 1)
    assert state.advisory is None


def test_encoded_key_matches(tmp_path: Path) -> None:
    tool = write_tool(tmp_path / "t.xml", PROBE_TOOL.replace('id="patch_probe"', 'id="Patch_Probe"'))
    rel = "_local/!patch_!probe/1.0+galaxy0.yml"
    assert states_of(
        load_db(write_collection(tmp_path / "c", {rel: security_doc(QUOTE_LABEL)})).apply_patches(tool)
    ) == ["applied"]


def test_patching_twice_equals_once(tmp_path: Path, probe: XmlToolSource) -> None:
    db = load_db(write_collection(tmp_path / "c", {LOCAL_PROBE: security_doc(QUOTE_LABEL)}))
    once = db.apply_patches(probe)
    text = once.to_string()
    assert db.apply_patches(once) is once
    assert states_of(once) == ["already_applied"]
    assert once.to_string() == text


def test_stacked_collections_apply_in_order(tmp_path: Path, probe: XmlToolSource) -> None:
    first = write_collection(tmp_path / "first", {LOCAL_PROBE: security_doc(QUOTE_LABEL)}, name="first")
    second = write_collection(
        tmp_path / "second", {LOCAL_PROBE: security_doc(text_op("echo '$label'", "echo -- '$label'"))}, name="second"
    )

    patched = load_db(first, second).apply_patches(probe)
    assert "echo -- '$label' >>" in command_text(patched.parse_command())
    assert [(s.collection.name, s.state) for s in patch_states(patched)] == [
        ("first", "applied"),
        ("second", "applied"),
    ]

    # the second's anchor isn't there yet; its mismatch doesn't block the first
    patched = load_db(second, first).apply_patches(probe)
    assert "echo '$label' >>" in command_text(patched.parse_command())
    assert [(s.collection.name, s.state) for s in patch_states(patched)] == [
        ("second", "mismatch"),
        ("first", "applied"),
    ]


@pytest.mark.parametrize(
    "series,state", [("26.0", "skipped"), ("26.1", "applied"), ("27.0", "applied"), (None, "applied")]
)
def test_needed_from_gate(tmp_path: Path, probe: XmlToolSource, series: str | None, state: str) -> None:
    db = load_db(write_collection(tmp_path / "c", {LOCAL_PROBE: compat_doc(QUOTE_LABEL)}), galaxy_series=series)
    patched = db.apply_patches(probe)
    assert states_of(patched) == [state]
    assert (patched is probe) == (state == "skipped")


@pytest.mark.parametrize("series", ["26", "26.1.0", "dev"])
def test_invalid_galaxy_series(tmp_path: Path, series: str) -> None:
    with pytest.raises(ValueError):
        load_db(tmp_path, galaxy_series=series)


def test_mixed_file_evaluates_kinds_separately(tmp_path: Path, probe: XmlToolSource) -> None:
    doc = security_doc(
        {**QUOTE_LABEL, "kind": "security"},
        {**text_op("absent anchor", "x"), "kind": "compat"},
        kind="mixed",
        needed_from="26.1",
        galaxy_change=GALAXY_CHANGE,
        upstream=[{**UPSTREAM, "kind": "security"}],
    )
    patched = load_db(write_collection(tmp_path / "c", {LOCAL_PROBE: doc})).apply_patches(probe)
    assert [(s.kind, s.state) for s in patch_states(patched)] == [("security", "applied"), ("compat", "mismatch")]
    assert "echo '$label' >>" in command_text(patched.parse_command())


def test_reproducibility_cap_demotes_to_advisory(tmp_path: Path, probe: XmlToolSource) -> None:
    db = load_db(
        write_collection(tmp_path / "c", {LOCAL_PROBE: security_doc(QUOTE_LABEL)}), reproducibility="rejects_inputs"
    )
    assert db.apply_patches(probe) is probe
    (state,) = patch_states(probe)
    assert state.state == "advisory" and state.advisory is not None
    assert (state.advisory.code, state.advisory.action, state.advisory.level) == (
        "reproducibility_above_cap",
        "enable_policy",
        "must_fix",
    )
    assert "unusual_inputs" in (state.advisory.message or "")
    assert "echo $label >>" in command_text(probe.parse_command())


@pytest.mark.parametrize("enabled", [False, True])
def test_requirement_changes_policy(tmp_path: Path, enabled: bool) -> None:
    tool = write_tool(tmp_path / "req.xml", REQUIREMENT_TOOL)
    doc = security_doc(REQUIREMENT_OP, reproducibility="ordinary_inputs", changes_requirements=True)
    db = load_db(write_collection(tmp_path / "c", {LOCAL_PROBE: doc}), requirement_changes=enabled)
    result = db.apply_patches(tool)
    (state,) = patch_states(result)
    if enabled:
        assert state.state == "applied" and state.changes_requirements
        assert 'version="1.1"' in result.to_string()
    else:
        assert result is tool
        assert state.state == "advisory" and state.advisory is not None
        assert state.advisory.code == "requirement_changes_disabled"


def test_policy_and_series_change_the_digest(tmp_path: Path) -> None:
    root = write_collection(tmp_path / "c", {LOCAL_PROBE: security_doc(QUOTE_LABEL)})
    configs: list[dict[str, Any]] = [
        {},
        {"reproducibility": "rejects_inputs"},
        {"requirement_changes": True},
        {"galaxy_series": "26.1"},
    ]
    digests = {load_db(root, **config).digest_for(LOCAL_KEY) for config in configs}
    assert len(digests) == len(configs) and None not in digests
    tokens = {load_db(root, **config).token() for config in configs}
    assert len(tokens) == len(configs)


def test_digests_follow_file_content(tmp_path: Path) -> None:
    root = write_collection(tmp_path / "c", {LOCAL_PROBE: security_doc(QUOTE_LABEL)})
    db = load_db(root)
    before = (db.digest_for(LOCAL_KEY), db.collections_summary().collections[0].digest, db.token())
    write_collection(root, {LOCAL_PROBE: security_doc(QUOTE_LABEL, reproducibility_doc="Other doc.")})
    db = load_db(root)
    after = (db.digest_for(LOCAL_KEY), db.collections_summary().collections[0].digest, db.token())
    assert all(b != a for b, a in zip(before, after))


def test_collection_digest_ignores_declared_digest(tmp_path: Path) -> None:
    declared = write_collection(tmp_path / "a", {LOCAL_PROBE: security_doc(QUOTE_LABEL)}, extra={"digest": "0" * 64})
    plain = write_collection(tmp_path / "b", {LOCAL_PROBE: security_doc(QUOTE_LABEL)})
    (summary,) = load_db(declared).collections_summary().collections
    assert (summary.name, summary.version) == ("test-patches", "2026.11.25")
    assert summary.digest != "0" * 64
    assert summary.digest == load_db(plain).collections_summary().collections[0].digest


@pytest.mark.parametrize("covered", [True, False])
def test_verified_from_coverage(
    tmp_path: Path, probe: XmlToolSource, covered: bool, caplog: pytest.LogCaptureFixture
) -> None:
    sha = sha256_text(probe.to_string()) if covered else "0" * 64
    root = write_collection(
        tmp_path / "c",
        {LOCAL_PROBE: security_doc(QUOTE_LABEL)},
        coverage={"_local/patch_probe/1.0+galaxy0.json": [sha]},
    )
    db = load_db(root)
    with caplog.at_level(logging.DEBUG, logger="galaxy.tool_util.patches"):
        patched = db.apply_patches(probe)
    (state,) = patch_states(patched)
    assert state.verified is covered
    levels = {r.levelname for r in caplog.records if "patch_probe" in r.getMessage()}
    assert levels == ({"INFO"} if covered else {"WARNING"})


DRILL_DOWN_OLD = (
    '<param name="parameter" type="drill_down" '
    'from_file="../test/functional/tool-data/gx_drill_down_from_file_options.xml"/>'
)
DRILL_DOWN_NEW = """<param name="parameter" type="drill_down">
    <options>
        <option name="Heading 1" value="heading1">
            <option name="Option 1" value="option1"/>
            <option name="Option 2" value="option2"/>
        </option>
        <option name="Option 3" value="option3"/>
    </options>
</param>"""


def test_drill_down_from_file_compat_fixture(tmp_path: Path) -> None:
    tool = get_tool_source(functional_test_tool_path("parameters/gx_drill_down_from_file.xml"))
    op = {
        "replace_element": {
            "path": "inputs/param[@name='parameter']",
            "old": DRILL_DOWN_OLD,
            "new": DRILL_DOWN_NEW,
            "occurrences": 1,
        }
    }
    doc = compat_doc(op, reproducibility_reason="options inlined verbatim from the options file")
    root = write_collection(tmp_path / "c", {"_local/gx_drill_down_from_file/1.0.0.yml": doc})

    patched = load_db(root, galaxy_series="26.1").apply_patches(tool)

    assert states_of(patched) == ["applied"]
    assert "from_file=" not in patched.to_string()
    # the expanded macro output is kept
    assert '<data name="output" format="txt"/>' in patched.to_string()
    assert patched.macro_paths == tool.macro_paths and patched.macro_paths
    (page,) = patched.parse_input_pages().page_sources
    (param,) = page.parse_input_sources()
    options = param.parse_drill_down_static_options()
    assert options is not None
    assert [o["value"] for o in options[0]["options"]] == ["option1", "option2"]


@dataclass
class IdentifierInput:
    element_identifier: str
    safe_element_identifier: str


CLEAN_IDENTIFIER_HELPER = (
    "#import re\n"
    "#def clean_identifier($identifier)\n"
    "#return re.sub('[^A-Za-z0-9._-]', '_', str($identifier))\n"
    "#end def\n"
)


def test_identifier_helper_fixture(tmp_path: Path) -> None:
    tool = get_tool_source(functional_test_tool_path("identifier_single.xml"))
    ops = [
        text_op("echo 'identifier ", CLEAN_IDENTIFIER_HELPER + "echo 'identifier "),
        text_op(
            "'identifier $input1.element_identifier'", "'identifier ${clean_identifier($input1.element_identifier)}'"
        ),
    ]
    db = load_db(write_collection(tmp_path / "c", {"_local/identifier_single/1.0.0.yml": security_doc(*ops)}))

    patched = db.apply_patches(tool)

    assert states_of(patched) == ["applied"]
    command = patched.parse_command()
    assert command is not None and command.count("#def clean_identifier") == 1
    input1 = IdentifierInput(element_identifier="a b;c", safe_element_identifier="x")
    rendered = fill_template(command, context={"input1": input1})
    assert "echo 'identifier a_b_c' > 'output1'" in rendered
    assert db.apply_patches(patched) is patched
    assert states_of(patched) == ["already_applied"]


@pytest.mark.parametrize(
    "variant,expected",
    [
        ("vulnerable", [("applied", "partial_fix")]),
        ("fixed", [("already_applied", None)]),
        ("drifted", [("mismatch", "revision_mismatch"), ("advisory", "partial_fix")]),
    ],
)
def test_ops_with_advisory_display(tmp_path: Path, variant: str, expected: list[tuple[str, str | None]]) -> None:
    content = {
        "vulnerable": PROBE_TOOL,
        "fixed": PROBE_TOOL.replace("echo $label", "echo '$label'"),
        "drifted": PROBE_TOOL.replace("echo $label", 'echo "$label"'),
    }[variant]
    tool = write_tool(tmp_path / "t.xml", content)
    doc = security_doc(QUOTE_LABEL, advisory={**ADVISORY, "code": "partial_fix"})
    result = load_db(write_collection(tmp_path / "c", {LOCAL_PROBE: doc})).apply_patches(tool)
    assert [(s.state, s.advisory.code if s.advisory else None) for s in patch_states(result)] == expected


def test_mismatch_suggests_revision_update(tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
    tool = write_tool(tmp_path / "t.xml", PROBE_TOOL.replace("echo $label", 'echo "$label"'))
    db = load_db(write_collection(tmp_path / "c", {LOCAL_PROBE: security_doc(QUOTE_LABEL)}))
    with caplog.at_level(logging.DEBUG, logger="galaxy.tool_util.patches"):
        assert db.apply_patches(tool) is tool
    (state,) = patch_states(tool)
    assert state.state == "mismatch" and state.detail and state.advisory is not None
    assert (state.advisory.code, state.advisory.action, state.advisory.vulnerable) == (
        "revision_mismatch",
        "update_revision",
        "unknown",
    )
    assert "latest installable revision" in (state.advisory.message or "")
    assert any(r.levelno == logging.WARNING and "mismatch" in r.getMessage() for r in caplog.records)


def test_advisory_only_file_uses_codes_table(tmp_path: Path, probe: XmlToolSource) -> None:
    doc = security_doc(**ADVISORY_ONLY, advisory={**ADVISORY, "code": "partial_fix"})
    db = load_db(write_collection(tmp_path / "c", {LOCAL_PROBE: doc}, codes=CODES))
    assert db.apply_patches(probe) is probe
    (state,) = patch_states(probe)
    assert state.state == "advisory" and state.advisory is not None
    assert (state.advisory.level, state.advisory.message, state.advisory.vulnerable) == (
        "must_fix",
        "Upgrade to 1.0+galaxy1 or later.",
        True,
    )


@pytest.mark.parametrize(
    "content",
    [
        pytest.param("kind: [", id="yaml_syntax"),
        pytest.param(yaml.safe_dump(security_doc(QUOTE_LABEL, kind="bogus")), id="schema"),
        pytest.param(
            yaml.safe_dump(security_doc(**ADVISORY_ONLY, advisory={**ADVISORY, "code": "nope"})), id="unknown_code"
        ),
        pytest.param(
            yaml.safe_dump(
                security_doc(**ADVISORY_ONLY, advisory={**ADVISORY, "code": "partial_fix", "action": "info"})
            ),
            id="action_not_allowed_by_code",
        ),
        pytest.param(
            yaml.safe_dump(
                security_doc(**ADVISORY_ONLY, advisory={**ADVISORY, "code": "partial_fix", "expanded_sha256": "0" * 64})
            ),
            id="expanded_sha256_outside_override",
        ),
    ],
)
def test_invalid_file_loads_tool_unpatched(
    tmp_path: Path, probe: XmlToolSource, content: str, caplog: pytest.LogCaptureFixture
) -> None:
    db = load_db(write_collection(tmp_path / "c", {LOCAL_PROBE: content}, codes=CODES))
    with caplog.at_level(logging.ERROR, logger="galaxy.tool_util.patches"):
        assert db.apply_patches(probe) is probe
    assert probe.patch_state is not None and probe.patch_state.digest is not None
    assert states_of(probe) == []
    assert any(LOCAL_PROBE in r.getMessage() for r in caplog.records if r.levelno == logging.ERROR)


def test_walk_refuses_non_canonical_and_bundled_keys(tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
    doc = security_doc(QUOTE_LABEL)
    files = {
        "Owner1/repo_a/patch_probe/1.0.yml": doc,
        "_local/!c!o!n!v!e!r!t!e!r_bed_to_gff/1.0.yml": doc,
        "_local/__x/1.0.yml": doc,
        "_local/patch_probe/1.0+galaxy0.yaml": doc,
        LOCAL_PROBE: doc,
    }
    root = write_collection(tmp_path / "c", files)
    with caplog.at_level(logging.ERROR, logger="galaxy.tool_util.patches"):
        db = load_db(root)
    assert db.digest_for(("Owner1", "repo_a", "patch_probe", "1.0")) is None
    assert db.digest_for(("_local", "CONVERTER_bed_to_gff", "1.0")) is None
    assert db.digest_for(("_local", "__x", "1.0")) is None
    assert db.digest_for(LOCAL_KEY) is not None
    assert len([r for r in caplog.records if r.levelno >= logging.ERROR]) == 3


def test_unknown_collection_format_is_skipped(tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
    bad = write_collection(tmp_path / "bad", {LOCAL_PROBE: security_doc(QUOTE_LABEL)}, format_version=2)
    good = write_collection(tmp_path / "good", {LOCAL_PROBE: security_doc(QUOTE_LABEL)}, name="good")
    with caplog.at_level(logging.ERROR, logger="galaxy.tool_util.patches"):
        db = load_db(bad, tmp_path / "missing", good)
    assert [c.name for c in db.collections_summary().collections] == ["good"]
    errors = [r.getMessage() for r in caplog.records if r.levelno >= logging.ERROR]
    assert len(errors) == 2 and "format_version" in errors[0]


def test_builtin_collection_is_empty(tmp_path: Path) -> None:
    (summary,) = load_tool_patch_database(["builtin"]).collections_summary().collections
    (empty,) = load_db(write_collection(tmp_path / "empty", {})).collections_summary().collections
    assert summary.name == "galaxy-builtin"
    assert summary.digest == empty.digest


@pytest.mark.parametrize(
    "dirstate,requires", [(DIRSTATE_V1, "store\n"), (DIRSTATE_V2, "dirstate-v2\nstore\n")], ids=["v1", "v2"]
)
@pytest.mark.parametrize("changeset", [NODE_HEX[:12], NODE_HEX], ids=["short", "full"])
def test_override_for_checked_out_changeset(tmp_path: Path, dirstate: bytes, requires: str, changeset: str) -> None:
    tool = shed_repo_tool(tmp_path, dirstate, requires)
    override = f"{SHED_PROBE}/@{changeset}.yml"
    root = write_collection(
        tmp_path / "c", {f"{SHED_PROBE}.yml": security_doc(QUOTE_LABEL), override: security_doc(OVERRIDE_OP)}
    )
    db = load_db(root)

    patched = db.apply_patches(tool, guid=SHED_GUID)

    (state,) = patch_states(patched)
    assert state.path == f"patches/{override}"
    command = patched.parse_command()
    assert command is not None and "cat -- '$input1'" in command and "echo $label >>" in command
    assert patched.patch_state is not None
    assert patched.patch_state.digest == db.digest_for(SHED_KEY, NODE_HEX)
    assert db.digest_for(SHED_KEY, NODE_HEX) != db.digest_for(SHED_KEY)


def test_tool_digest_matches_applied_digest(tmp_path: Path) -> None:
    tool = shed_repo_tool(tmp_path)
    root = write_collection(
        tmp_path / "c", {f"{SHED_PROBE}.yml": security_doc(QUOTE_LABEL), OVERRIDE_REL: security_doc(OVERRIDE_OP)}
    )
    db = load_db(root)
    patched = db.apply_patches(tool, guid=SHED_GUID)
    assert patched.patch_state is not None
    assert db.tool_digest(SHED_KEY, str(tool.source_path)) == patched.patch_state.digest
    assert db.tool_digest(SHED_KEY, str(tmp_path / "elsewhere")) == db.digest_for(SHED_KEY)


def test_changeset_follows_dirstate_rewrites(tmp_path: Path) -> None:
    tool = shed_repo_tool(tmp_path)
    root = write_collection(
        tmp_path / "c", {f"{SHED_PROBE}.yml": security_doc(QUOTE_LABEL), OVERRIDE_REL: security_doc(OVERRIDE_OP)}
    )
    db = load_db(root)
    (state,) = patch_states(db.apply_patches(tool, guid=SHED_GUID))
    assert state.path == f"patches/{OVERRIDE_REL}"

    # an in-place repository update checks out another changeset
    dirstate = tmp_path / "repo" / ".hg" / "dirstate"
    dirstate.write_bytes(bytes(range(100, 120)) + b"\0" * 20)
    stat = dirstate.stat()
    os.utime(dirstate, ns=(stat.st_atime_ns, stat.st_mtime_ns + 1_000_000_000))
    updated = get_tool_source(config_file=str(tool.source_path))

    (state,) = patch_states(db.apply_patches(updated, guid=SHED_GUID))
    assert state.path == f"patches/{SHED_PROBE}.yml"


@pytest.mark.parametrize(
    "guid,tool_id,version,key",
    [
        (SHED_GUID, "ignored", "ignored", SHED_KEY),
        (None, "patch_probe", "1.0+galaxy0", LOCAL_KEY),
        ("patch_probe", "patch_probe", "1.0+galaxy0", LOCAL_KEY),
        (None, "patch_probe", None, None),
    ],
)
def test_key_from_ids(guid: str | None, tool_id: str | None, version: str | None, key: tuple[str, ...] | None) -> None:
    assert key_from_ids(guid, tool_id, version) == key


@pytest.mark.parametrize("case", ["other_changeset", "override_mismatch", "unreadable_dirstate", "no_repository"])
def test_version_file_without_a_usable_override(tmp_path: Path, case: str) -> None:
    if case == "no_repository":
        tool = write_tool(tmp_path / "plain" / "probe.xml")
    else:
        tool = shed_repo_tool(tmp_path, b"" if case == "unreadable_dirstate" else DIRSTATE_V1)
    override_name = "ffffffffffff" if case == "other_changeset" else NODE_HEX[:12]
    override_op = text_op("absent anchor", "x") if case == "override_mismatch" else OVERRIDE_OP
    root = write_collection(
        tmp_path / "c",
        {
            f"{SHED_PROBE}.yml": security_doc(QUOTE_LABEL),
            f"{SHED_PROBE}/@{override_name}.yml": security_doc(override_op),
        },
    )

    patched = load_db(root).apply_patches(tool, guid=SHED_GUID)

    (state,) = patch_states(patched)
    assert (state.state, state.path) == ("applied", f"patches/{SHED_PROBE}.yml")
    assert "echo '$label' >>" in command_text(patched.parse_command())


@pytest.mark.parametrize("matches", [True, False])
def test_advisory_override_checks_expanded_sha256(tmp_path: Path, matches: bool) -> None:
    tool = shed_repo_tool(tmp_path)
    sha = sha256_text(tool.to_string()) if matches else "0" * 64
    override = security_doc(**ADVISORY_ONLY, advisory={**ADVISORY, "expanded_sha256": sha})
    root = write_collection(tmp_path / "c", {f"{SHED_PROBE}.yml": security_doc(QUOTE_LABEL), OVERRIDE_REL: override})
    result = load_db(root).apply_patches(tool, guid=SHED_GUID)
    assert states_of(result) == (["advisory"] if matches else ["applied"])


def test_symlinked_override(tmp_path: Path) -> None:
    tool = shed_repo_tool(tmp_path)
    target = f"{SHED_PROBE}/@abcdefabcdef.yml"
    root = write_collection(
        tmp_path / "c", {f"{SHED_PROBE}.yml": security_doc(QUOTE_LABEL), target: security_doc(OVERRIDE_OP)}
    )
    os.symlink("@abcdefabcdef.yml", root / "patches" / OVERRIDE_REL)

    patched = load_db(root).apply_patches(tool, guid=SHED_GUID)

    (state,) = patch_states(patched)
    assert state.path == f"patches/{OVERRIDE_REL}"
    assert state.digest == hashlib.sha256((root / "patches" / target).read_bytes()).hexdigest()
    assert "cat -- '$input1'" in command_text(patched.parse_command())


def test_symlink_outside_the_collection_is_refused(tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
    tool = shed_repo_tool(tmp_path)
    root = write_collection(tmp_path / "c", {f"{SHED_PROBE}.yml": security_doc(QUOTE_LABEL)})
    outside = tmp_path / "outside.yml"
    outside.write_text(yaml.safe_dump(security_doc(OVERRIDE_OP)))
    link = root / "patches" / OVERRIDE_REL
    link.parent.mkdir()
    os.symlink(outside, link)
    with caplog.at_level(logging.ERROR, logger="galaxy.tool_util.patches"):
        db = load_db(root)
    assert any("outside" in r.getMessage() for r in caplog.records if r.levelno >= logging.ERROR)
    (state,) = patch_states(db.apply_patches(tool, guid=SHED_GUID))
    assert state.path == f"patches/{SHED_PROBE}.yml"


def test_concurrent_apply_parses_each_file_once(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    db = load_db(write_collection(tmp_path / "c", {LOCAL_PROBE: security_doc(QUOTE_LABEL)}))
    parses = []
    original = patch_collection.parse_patch_yaml

    def counting(data: bytes) -> Any:
        parses.append(1)
        return original(data)

    monkeypatch.setattr(patch_collection, "parse_patch_yaml", counting)
    sources = [write_tool(tmp_path / f"t{i}" / "probe.xml") for i in range(16)]
    with ThreadPoolExecutor(max_workers=8) as executor:
        results = list(executor.map(db.apply_patches, sources))
    assert all(states_of(r) == ["applied"] for r in results)
    assert len(parses) == 1


@pytest.mark.skipif(shutil.which("hg") is None, reason="Mercurial is not installed")
@pytest.mark.parametrize("v2", [False, True])
def test_dirstate_of_real_repository(tmp_path: Path, v2: bool) -> None:
    repo = tmp_path / "repo"
    # pure-Python Mercurial needs the slow path allowed for dirstate-v2
    config = ["--config", "storage.dirstate-v2.slow-path=allow"]
    flag = f"format.use-dirstate-v2={'yes' if v2 else 'no'}"
    subprocess.run(["hg", *config, "--config", flag, "init", str(repo)], check=True)
    (repo / "a.txt").write_text("a")
    hg = ["hg", "--cwd", str(repo), *config, "--config", "ui.username=test"]
    subprocess.run([*hg, "commit", "-A", "-m", "a"], check=True, capture_output=True)
    node = subprocess.run([*hg, "log", "-r", ".", "-T", "{node}"], check=True, capture_output=True, text=True).stdout
    assert ("dirstate-v2" in (repo / ".hg" / "requires").read_text()) == v2
    assert read_working_parent(str(repo)) == node


def test_override_keeps_its_security_fix_when_its_compat_unit_mismatches(tmp_path: Path) -> None:
    tool = shed_repo_tool(tmp_path)
    override = security_doc(
        {**OVERRIDE_OP, "kind": "security"},
        {**text_op("absent anchor", "x"), "kind": "compat"},
        kind="mixed",
        needed_from="26.1",
        galaxy_change=GALAXY_CHANGE,
        upstream=[{**UPSTREAM, "kind": "security"}],
    )
    root = write_collection(
        tmp_path / "c", {f"{SHED_PROBE}.yml": security_doc(text_op("absent anchor", "y")), OVERRIDE_REL: override}
    )

    patched = load_db(root).apply_patches(tool, guid=SHED_GUID)

    assert {(s.kind, s.state, s.path) for s in patch_states(patched)} == {
        ("security", "applied", f"patches/{OVERRIDE_REL}"),
        ("compat", "mismatch", f"patches/{OVERRIDE_REL}"),
    }
    assert "cat -- '$input1'" in command_text(patched.parse_command())


def test_digests_follow_coverage_and_codes(tmp_path: Path) -> None:
    root = write_collection(tmp_path / "c", {LOCAL_PROBE: security_doc(QUOTE_LABEL)})
    db = load_db(root)
    digests = [(db.digest_for(LOCAL_KEY), db.token())]
    write_collection(root, {}, coverage={"_local/patch_probe/1.0+galaxy0.json": ["0" * 64]})
    db = load_db(root)
    digests.append((db.digest_for(LOCAL_KEY), db.token()))
    write_collection(root, {}, codes=CODES)
    db = load_db(root)
    digests.append((db.digest_for(LOCAL_KEY), db.token()))
    assert len(set(digests)) == 3


@pytest.mark.parametrize("position", ["first", "before:b"])
def test_add_element_keeps_mixed_text_once(tmp_path: Path, position: str) -> None:
    tool = write_tool(
        tmp_path / "probe.xml", PROBE_TOOL.replace("<help>Old help.</help>", "<help>Real text <b>x</b></help>")
    )
    op = {"add_element": {"parent": "help", "new": "<i/>", "position": position, "occurrences": 1}}
    result = run(tool, op)
    assert result.tree is not None
    help_el = result.tree.getroot().find("help")
    assert help_el is not None
    assert "".join(help_el.itertext()).count("Real text") == 1


def test_summary_counts_applied_states(tmp_path: Path, probe: XmlToolSource) -> None:
    db = load_db(write_collection(tmp_path / "c", {LOCAL_PROBE: security_doc(QUOTE_LABEL)}))
    db.apply_patches(probe)
    db.apply_patches(db.apply_patches(write_tool(tmp_path / "again" / "probe.xml")))
    assert db.summary().endswith("; applied 2, already_applied 1, mismatch 0, skipped 0, advisory 0")
    assert db.summary().startswith("tool patches: test-patches 2026.11.25 digest ")


def test_engine_version_is_in_the_digests(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    db = load_db(write_collection(tmp_path / "c", {LOCAL_PROBE: security_doc(QUOTE_LABEL)}))
    before = db.digest_for(LOCAL_KEY)
    monkeypatch.setattr("galaxy.tool_util.patches.database.ENGINE_VERSION", 2)
    assert db.digest_for(LOCAL_KEY) != before
