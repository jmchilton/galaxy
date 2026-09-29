"""Resolve and identify tool license agreements.

An agreement is identified by ``agreement_hash``: SHA-256 over a versioned
canonical JSON document of the affirmation and the terms the user is shown.
``id``, ``version``, ``label`` and ``url`` are display metadata and do not
contribute, so two tools shipping the same displayed agreement share one
acceptance, and fixing display metadata does not re-prompt anyone.

The affirmation is canonicalized by the ``LicenseAgreement`` model. The
canonicalization below, the model's, and ``AGREEMENT_HASH_SCHEMA`` must not
change in place - a different canonical form needs a new schema version.
"""

import hashlib
import json
import os
import textwrap
from dataclasses import dataclass

from packaging.version import Version

from galaxy.tool_util_models.tool_source import LicenseAgreement
from galaxy.util.path import (
    safe_contains,
    StrPath,
)

AGREEMENT_HASH_SCHEMA = 1
LICENSE_AGREEMENT_MIN_PROFILE = "26.2"


def _normalize_newlines(text: str) -> str:
    return text.replace("\r\n", "\n").replace("\r", "\n")


def canonical_terms(text: str) -> str:
    """Normalize line endings, empty whitespace-only lines and drop leading and trailing blank lines.

    Whitespace-only lines are emptied so file terms match inline terms, where
    dedent already does the same. Everything else is kept.
    """
    lines = ["" if line.strip() == "" else line for line in _normalize_newlines(text).split("\n")]
    while lines and lines[0] == "":
        lines.pop(0)
    while lines and lines[-1] == "":
        lines.pop()
    return "\n".join(lines)


def canonical_inline_terms(text: str) -> str:
    """Canonical terms for inline ``<text>``, which is additionally dedented to drop XML indentation."""
    return canonical_terms(textwrap.dedent(_normalize_newlines(text)))


def agreement_hash(affirmation: str, terms: str) -> str:
    """Hash canonical affirmation and terms - both must already be canonical."""
    payload = json.dumps(
        {
            "affirmation": affirmation,
            "schema": AGREEMENT_HASH_SCHEMA,
            "terms": terms,
        },
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


@dataclass(frozen=True)
class ResolvedLicenseAgreement:
    agreement: LicenseAgreement
    terms: str
    agreement_hash: str


def _read_terms_file(requirement: LicenseAgreement, tool_dir: StrPath | None) -> str:
    path = requirement.path
    assert path is not None
    if os.path.isabs(path):
        raise ValueError(f"License agreement [{requirement.id}] path [{path}] must be relative to the tool directory")
    if tool_dir is None:
        raise ValueError(f"License agreement [{requirement.id}] path [{path}] requires a tool directory")
    # The tool directory itself may be reached through a symlink; only the license path must stay inside it.
    tool_dir = os.path.realpath(tool_dir)
    if not safe_contains(tool_dir, path):
        raise ValueError(f"License agreement [{requirement.id}] path [{path}] escapes the tool directory")
    try:
        with open(os.path.join(tool_dir, path), "rb") as f:
            contents = f.read()
    except OSError as e:
        raise ValueError(f"Cannot read license agreement [{requirement.id}] file [{path}]: {e}")
    try:
        # utf-8-sig drops a leading byte order mark, which is invisible but would change the hash.
        return contents.decode("utf-8-sig")
    except UnicodeDecodeError:
        raise ValueError(f"License agreement [{requirement.id}] file [{path}] is not valid UTF-8")


def resolve_license_agreement(requirement: LicenseAgreement, tool_dir: StrPath | None) -> ResolvedLicenseAgreement:
    """Load the terms (reading ``path`` relative to ``tool_dir``) and compute the agreement hash."""
    if requirement.text is not None:
        terms = canonical_inline_terms(requirement.text)
    else:
        terms = canonical_terms(_read_terms_file(requirement, tool_dir))
    if not terms:
        raise ValueError(f"License agreement [{requirement.id}] terms are empty")
    return ResolvedLicenseAgreement(
        agreement=requirement,
        terms=terms,
        agreement_hash=agreement_hash(requirement.affirmation, terms),
    )


def check_license_agreement_profile(profile: str, license_agreements: list[LicenseAgreement]) -> None:
    if license_agreements and Version(profile) < Version(LICENSE_AGREEMENT_MIN_PROFILE):
        raise ValueError(
            f"License agreements require tool profile {LICENSE_AGREEMENT_MIN_PROFILE} or newer, tool declares profile {profile}"
        )
