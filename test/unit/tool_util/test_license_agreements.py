import os

import pytest

from galaxy.tool_util.license_agreements import (
    agreement_hash,
    canonical_inline_terms,
    canonical_terms,
    check_license_agreement_profile,
    resolve_license_agreement,
)
from galaxy.tool_util.model_factory import parse_tool
from galaxy.tool_util.parser.xml import XmlToolSource
from galaxy.tool_util.parser.yaml import YamlToolSource
from galaxy.util import parse_xml_string

TERMS = "This software is free for non-commercial use.\n\nCommercial use requires a license."
AFFIRMATION = "I certify that I am not using this tool for commercial purposes."


def _tool_source(requirements: str, profile: str = "26.2") -> XmlToolSource:
    contents = f"""<tool id="license_tool" name="License Tool" version="1.0" profile="{profile}">
    <requirements>
        {requirements}
    </requirements>
    <command>echo hi</command>
    <inputs />
    <outputs />
</tool>
"""
    # Tool loading preserves whitespace (see galaxy.util.xml_macros), which dedent relies on.
    return XmlToolSource(parse_xml_string(contents, strip_whitespace=False).getroottree())


def _inline(
    affirmation: str = AFFIRMATION,
    text: str | None = None,
    attributes: str = 'id="nc" version="1"',
    label: str = "Non-commercial use only",
) -> str:
    if text is None:
        text = """
            This software is free for non-commercial use.

            Commercial use requires a license.
        """
    return f"""<license_agreement {attributes}>
            <label>{label}</label>
            <affirmation>{affirmation}</affirmation>
            <text><![CDATA[{text}]]></text>
        </license_agreement>"""


def _path(path: str = "license.txt", attributes: str = 'id="nc" version="1"') -> str:
    return f"""<license_agreement {attributes} path="{path}">
            <label>Non-commercial use only</label>
            <url>https://example.org/license</url>
            <affirmation>{AFFIRMATION}</affirmation>
        </license_agreement>"""


def _parse_one(requirements: str):
    (agreement,) = _tool_source(requirements).parse_license_agreements()
    return agreement


def _write(tmp_path, name: str, content: bytes) -> str:
    (tmp_path / name).write_bytes(content)
    return str(tmp_path)


def test_parse_inline_agreement():
    agreement = _parse_one(_inline())
    assert agreement.id == "nc"
    assert agreement.version == "1"
    assert agreement.label == "Non-commercial use only"
    assert agreement.affirmation == AFFIRMATION
    assert agreement.binds == "submission"
    assert agreement.path is None
    assert agreement.url is None
    assert agreement.text is not None


def test_parse_path_agreement():
    agreement = _parse_one(_path())
    assert agreement.path == "license.txt"
    assert agreement.text is None
    assert agreement.url == "https://example.org/license"


def test_parse_binds_user():
    agreement = _parse_one(_inline(attributes='id="nc" version="1" binds="user"'))
    assert agreement.binds == "user"


def test_parse_invalid_binds():
    with pytest.raises(ValueError, match="binds"):
        _parse_one(_inline(attributes='id="nc" version="1" binds="job"'))


def test_parse_multiple_agreements():
    agreements = _tool_source(_inline() + _path(attributes='id="other" version="2"')).parse_license_agreements()
    assert [a.id for a in agreements] == ["nc", "other"]


def test_no_agreements():
    assert _tool_source('<requirement type="package">bwa</requirement>').parse_license_agreements() == []


def test_parse_requires_path_or_text():
    requirement = """<license_agreement id="nc" version="1">
            <label>Label</label>
            <affirmation>I agree.</affirmation>
        </license_agreement>"""
    with pytest.raises(ValueError, match="exactly one of"):
        _parse_one(requirement)


def test_parse_rejects_path_and_text():
    requirement = """<license_agreement id="nc" version="1" path="license.txt">
            <label>Label</label>
            <affirmation>I agree.</affirmation>
            <text>Terms</text>
        </license_agreement>"""
    with pytest.raises(ValueError, match="exactly one of"):
        _parse_one(requirement)


@pytest.mark.parametrize("attributes", ['version="1"', 'id="nc"'])
def test_parse_requires_id_and_version(attributes):
    with pytest.raises(ValueError):
        _parse_one(_inline(attributes=attributes))


def test_parse_requires_label():
    with pytest.raises(ValueError, match="label"):
        _parse_one(_inline(label=""))


def test_parse_requires_affirmation():
    with pytest.raises(ValueError, match="affirmation"):
        _parse_one(_inline(affirmation="   "))


def test_parse_rejects_multiline_affirmation():
    with pytest.raises(ValueError, match="single line"):
        _parse_one(_inline(affirmation="I agree\nto everything."))


def test_affirmation_is_stripped():
    assert _parse_one(_inline(affirmation=f"\n   {AFFIRMATION}  \n")).affirmation == AFFIRMATION


def test_canonical_terms_normalizes_line_endings_and_outer_blank_lines():
    assert canonical_terms("\n\n  \nline one  \r\n\r\n  line two\rline three\n\n \n") == (
        "line one  \n\n  line two\nline three"
    )


def test_canonical_inline_terms_dedents():
    assert canonical_inline_terms("\n    line one\n      line two\n    ") == "line one\n  line two"


def test_agreement_hash_stable_under_reindent():
    shallow = resolve_license_agreement(
        _parse_one(_inline(text=f"\n  {TERMS.replace(chr(10), chr(10) + '  ')}\n")), None
    )
    deep = resolve_license_agreement(
        _parse_one(_inline(text=f"\n            {TERMS.replace(chr(10), chr(10) + '            ')}\n        ")), None
    )
    assert shallow.terms == TERMS
    assert shallow.agreement_hash == deep.agreement_hash


def test_path_and_inline_agree(tmp_path):
    tool_dir = _write(tmp_path, "license.txt", f"\n\n{TERMS}\n\n".encode())
    from_path = resolve_license_agreement(_parse_one(_path()), tool_dir)
    inline = resolve_license_agreement(_parse_one(_inline()), None)
    assert from_path.terms == TERMS
    assert from_path.agreement_hash == inline.agreement_hash


def test_byte_identical_files_in_separate_directories_share_hash(tmp_path):
    (tmp_path / "a").mkdir()
    (tmp_path / "b").mkdir()
    first = _write(tmp_path / "a", "license.txt", TERMS.encode())
    second = _write(tmp_path / "b", "license.txt", TERMS.encode())
    assert (
        resolve_license_agreement(_parse_one(_path()), first).agreement_hash
        == resolve_license_agreement(_parse_one(_path(attributes='id="different" version="9"')), second).agreement_hash
    )


def test_crlf_and_lf_license_files_hash_identically(tmp_path):
    (tmp_path / "lf").mkdir()
    (tmp_path / "crlf").mkdir()
    lf = _write(tmp_path / "lf", "license.txt", f"{TERMS}\n".encode())
    crlf = _write(tmp_path / "crlf", "license.txt", f"{TERMS}\n".replace("\n", "\r\n").encode())
    agreement = _parse_one(_path())
    assert (
        resolve_license_agreement(agreement, lf).agreement_hash
        == resolve_license_agreement(agreement, crlf).agreement_hash
    )


def test_version_label_url_and_id_changes_do_not_change_hash():
    base = resolve_license_agreement(_parse_one(_inline()), None)
    changed = resolve_license_agreement(
        _parse_one(_inline(attributes='id="renamed" version="7" binds="user"', label="Another label")), None
    )
    assert base.agreement_hash == changed.agreement_hash


def test_affirmation_change_does_change_hash():
    base = resolve_license_agreement(_parse_one(_inline()), None)
    changed = resolve_license_agreement(_parse_one(_inline(affirmation="I have read and agree to these terms.")), None)
    assert base.agreement_hash != changed.agreement_hash


def test_terms_change_does_change_hash():
    base = resolve_license_agreement(_parse_one(_inline()), None)
    changed = resolve_license_agreement(_parse_one(_inline(text="Different terms.")), None)
    assert base.agreement_hash != changed.agreement_hash


def test_agreement_hash_contract():
    # Pinned: the canonicalization and hash domain must not change in place.
    assert agreement_hash("I agree.", "Terms.") == "6a0d4e924b4e239cd76cfe1f6614d916731f4e5b2a35aa239d65c70a377ad3fe"


def test_missing_license_path_fails(tmp_path):
    with pytest.raises(ValueError, match="license.txt"):
        resolve_license_agreement(_parse_one(_path()), str(tmp_path))


def test_invalid_utf8_license_file_fails(tmp_path):
    tool_dir = _write(tmp_path, "license.txt", b"\xff\xfe not utf-8")
    with pytest.raises(ValueError, match="UTF-8"):
        resolve_license_agreement(_parse_one(_path()), tool_dir)


def test_empty_license_file_fails(tmp_path):
    tool_dir = _write(tmp_path, "license.txt", b"\n  \n")
    with pytest.raises(ValueError, match="empty"):
        resolve_license_agreement(_parse_one(_path()), tool_dir)


def test_license_path_escaping_tool_dir_fails(tmp_path):
    (tmp_path / "tool").mkdir()
    _write(tmp_path, "license.txt", TERMS.encode())
    with pytest.raises(ValueError, match="tool directory"):
        resolve_license_agreement(_parse_one(_path(path="../license.txt")), str(tmp_path / "tool"))


def test_absolute_license_path_fails(tmp_path):
    tool_dir = _write(tmp_path, "license.txt", TERMS.encode())
    with pytest.raises(ValueError, match="relative"):
        resolve_license_agreement(_parse_one(_path(path=os.path.join(tool_dir, "license.txt"))), tool_dir)


def test_profile_below_26_2_rejected():
    tool_source = _tool_source(_inline(), profile="26.1")
    with pytest.raises(ValueError, match="26.2"):
        check_license_agreement_profile(tool_source.parse_profile(), tool_source.parse_license_agreements())


def test_profile_26_2_accepted():
    tool_source = _tool_source(_inline())
    check_license_agreement_profile(tool_source.parse_profile(), tool_source.parse_license_agreements())


def test_low_profile_without_agreements_accepted():
    check_license_agreement_profile("16.01", [])


def test_parsed_tool_includes_license_agreements():
    parsed = parse_tool(_tool_source(_inline() + _path(attributes='id="other" version="2" binds="user"')))
    assert [(a.id, a.binds, a.path) for a in parsed.license_agreements] == [
        ("nc", "submission", None),
        ("other", "user", "license.txt"),
    ]
    assert parsed.license_agreements[0].affirmation == AFFIRMATION


def test_relative_tool_dir_resolves(tmp_path, monkeypatch):
    _write(tmp_path, "license.txt", TERMS.encode())
    monkeypatch.chdir(tmp_path.parent)
    resolved = resolve_license_agreement(_parse_one(_path()), tmp_path.name)
    assert resolved.terms == TERMS


def test_symlink_escaping_tool_dir_fails(tmp_path):
    (tmp_path / "tool").mkdir()
    _write(tmp_path, "outside.txt", TERMS.encode())
    (tmp_path / "tool" / "license.txt").symlink_to(tmp_path / "outside.txt")
    with pytest.raises(ValueError, match="tool directory"):
        resolve_license_agreement(_parse_one(_path()), str(tmp_path / "tool"))


def test_symlinked_tool_dir_resolves(tmp_path):
    (tmp_path / "real").mkdir()
    _write(tmp_path / "real", "license.txt", TERMS.encode())
    (tmp_path / "linked").symlink_to(tmp_path / "real")
    assert resolve_license_agreement(_parse_one(_path()), str(tmp_path / "linked")).terms == TERMS


def test_utf8_bom_is_ignored(tmp_path):
    (tmp_path / "bom").mkdir()
    (tmp_path / "plain").mkdir()
    bom = _write(tmp_path / "bom", "license.txt", b"\xef\xbb\xbf" + TERMS.encode())
    plain = _write(tmp_path / "plain", "license.txt", TERMS.encode())
    agreement = _parse_one(_path())
    resolved = resolve_license_agreement(agreement, bom)
    assert resolved.terms == TERMS
    assert resolved.agreement_hash == resolve_license_agreement(agreement, plain).agreement_hash


def test_whitespace_only_lines_match_between_path_and_inline(tmp_path):
    tool_dir = _write(tmp_path, "license.txt", b"first\n   \nsecond")
    from_path = resolve_license_agreement(_parse_one(_path()), tool_dir)
    inline = resolve_license_agreement(_parse_one(_inline(text="\n    first\n       \n    second\n")), None)
    assert from_path.terms == inline.terms == "first\n\nsecond"


def test_empty_inline_text_fails():
    with pytest.raises(ValueError, match="empty"):
        resolve_license_agreement(_parse_one(_inline(text="\n   \n")), None)


def test_path_without_tool_dir_fails():
    with pytest.raises(ValueError, match="requires a tool directory"):
        resolve_license_agreement(_parse_one(_path()), None)


def test_yaml_tool_source_has_no_license_agreements():
    assert (
        YamlToolSource({"class": "GalaxyTool", "id": "t", "name": "t", "version": "1"}).parse_license_agreements() == []
    )
