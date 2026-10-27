"""Pure helpers for building comparison table columns; no database access."""

import re
from collections import defaultdict
from collections.abc import Mapping
from typing import (
    Any,
    NamedTuple,
    TypeVar,
)

from galaxy.schema.comparisons import (
    ComparisonColumn,
    ComparisonColumnRole,
)

NEW_PRIMARY_FILE_PREFIX = "__new_primary_file_"
PART_SEPARATOR = "|__part__|"
TRAILING_DIGITS = re.compile(r"\d+$")
IoValueT = TypeVar("IoValueT")


class ColumnSpec(NamedTuple):
    key: str
    label: str
    role: ComparisonColumnRole

    @classmethod
    def of_key(cls, key: str) -> "ColumnSpec":
        """Column of a role-prefixed key, e.g. ``output:out_file1``."""
        role, name = key.split(":", 1)
        column_role: ComparisonColumnRole = (
            "parameter" if role == "parameter" else "input" if role == "input" else "output"
        )
        return cls(key=key, label=name, role=column_role)


def normalize_io_name(name: str) -> str:
    """Fold discovered-primary and split-part association names to the declared output name."""
    if name.startswith(NEW_PRIMARY_FILE_PREFIX) and "|" in name:
        return name[len(NEW_PRIMARY_FILE_PREFIX) :].split("|", 1)[0]
    if PART_SEPARATOR in name:
        return name.split(PART_SEPARATOR, 1)[0]
    return name


def keyed_io(role: str, items: Mapping[str, IoValueT]) -> dict[str, IoValueT]:
    """Role-prefix normalized io names; an exact name wins over names folded into it."""
    keyed: dict[str, IoValueT] = {}
    for name, ref in items.items():
        normalized = normalize_io_name(name)
        key = f"{role}:{normalized}"
        if normalized == name:
            keyed[key] = ref
        else:
            keyed.setdefault(key, ref)
    return keyed


def multiple_input_members(ids_by_name: Mapping[str, Any]) -> dict[str, list[str]]:
    """Names a multiple data param records per dataset (``name1``, ``name2``...), by ``name``, in dataset order."""
    members: dict[str, list[tuple[int, str]]] = defaultdict(list)
    for name in ids_by_name:
        match = TRAILING_DIGITS.search(name)
        if not match:
            continue
        # a name like f11 may be f1 + 1 or f + 11; try every split
        for split in range(match.start(), len(name)):
            base, index = name[:split], name[split:]
            first = f"{base}1"
            if (
                base
                and not index.startswith("0")
                and base in ids_by_name
                and first in ids_by_name
                and ids_by_name[base] == ids_by_name[first]
            ):
                members[base].append((int(index), name))
                break
    return {base: [name for _, name in sorted(indexed)] for base, indexed in members.items()}


def align_columns(declared: Mapping[int, list[ColumnSpec]], newest_version: int) -> list[ComparisonColumn]:
    """Union of per-version columns, ordered by the newest version, with older-only columns last."""
    versions_by_key: dict[str, set[int]] = {}
    specs: dict[str, ColumnSpec] = {}
    duplicates: set[str] = set()
    order: list[str] = []
    ordered_versions = sorted(declared, key=lambda version: (version != newest_version, -version))
    for version in ordered_versions:
        seen_in_version: set[str] = set()
        for spec in declared[version]:
            if spec.key in seen_in_version:
                duplicates.add(spec.key)
                continue
            seen_in_version.add(spec.key)
            if spec.key not in specs:
                specs[spec.key] = spec
                order.append(spec.key)
            versions_by_key.setdefault(spec.key, set()).add(version)
    all_versions = set(declared)
    return [
        ComparisonColumn(
            key=key,
            label=specs[key].label,
            role=specs[key].role,
            present_in_versions=None if versions_by_key[key] == all_versions else sorted(versions_by_key[key]),
            duplicate=key in duplicates,
        )
        for key in order
    ]
