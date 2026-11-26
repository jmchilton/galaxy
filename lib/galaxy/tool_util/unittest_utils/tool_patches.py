"""Write tool patch collections for tests."""

import json
from pathlib import Path
from typing import Any

import yaml

UPSTREAM = {"repo": "galaxyproject/tools-iuc", "pr": 1, "merge_commit": "0123456789abcdef0123456789abcdef01234567"}


def write_collection(
    root: Path,
    files: dict[str, Any],
    *,
    name: str = "test-patches",
    format_version: int = 1,
    codes: dict[str, Any] | None = None,
    coverage: dict[str, list[str]] | None = None,
    extra: dict[str, Any] | None = None,
) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    metadata = {"name": name, "version": "2026.11.25", "format_version": format_version, **(extra or {})}
    (root / "collection.yml").write_text(yaml.safe_dump(metadata))
    for rel, doc in files.items():
        path = root / "patches" / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(doc if isinstance(doc, str) else yaml.safe_dump(doc))
    if codes is not None:
        (root / "codes.yml").write_text(yaml.safe_dump({"format_version": 1, "codes": codes}))
    for rel, shas in (coverage or {}).items():
        path = root / "coverage" / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"checked": [{"expanded_sha256": sha} for sha in shas]}))
    return root


def security_patch(ops: list[dict[str, Any]], reproducibility: str, doc: str, **extra: Any) -> dict[str, Any]:
    """A ``kind: security`` patch file document."""
    return {
        "format_version": 1,
        "kind": "security",
        "upstream": [UPSTREAM],
        "reproducibility": reproducibility,
        "reproducibility_doc": doc,
        "ops": ops,
        **extra,
    }


def replace_text_op(path: str, old: str, new: str, occurrences: int = 1) -> dict[str, Any]:
    return {"replace_text": {"path": path, "old": old, "new": new, "occurrences": occurrences}}
