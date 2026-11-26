"""Read the checked-out changeset of a Mercurial working copy without hg."""

import logging
import os

log = logging.getLogger(__name__)

DIRSTATE_V2_MARKER = b"dirstate-v2\n"
DIRSTATE_V2_REQUIREMENT = "dirstate-v2"
NODE_LENGTH = 20
# v1: p1 (20) + p2 (20); v2 docket: marker (12) + p1 (32, null padded) + p2 (32) + ...
_V1_HEADER = 2 * NODE_LENGTH
_V2_P1_END = len(DIRSTATE_V2_MARKER) + NODE_LENGTH


def find_repository_dir(start: str) -> str | None:
    """Nearest directory at or above start holding a ``.hg`` directory."""
    current = os.path.abspath(start)
    while True:
        if os.path.isdir(os.path.join(current, ".hg")):
            return current
        parent = os.path.dirname(current)
        if parent == current:
            return None
        current = parent


def _requires(hg_dir: str) -> set[str]:
    try:
        with open(os.path.join(hg_dir, "requires")) as f:
            return {line.strip() for line in f}
    except OSError:
        return set()


def read_working_parent(repo_dir: str) -> str | None:
    """Hex node of the working copy's first parent, or None if unknown."""
    hg_dir = os.path.join(repo_dir, ".hg")
    if not os.path.isdir(hg_dir):
        return None
    try:
        with open(os.path.join(hg_dir, "dirstate"), "rb") as f:
            header = f.read(len(DIRSTATE_V2_MARKER) + 2 * 32)
    except OSError as e:
        log.warning("tool patches: can't read the dirstate of %s: %s", repo_dir, e)
        return None
    if header.startswith(DIRSTATE_V2_MARKER):
        node = header[len(DIRSTATE_V2_MARKER) : _V2_P1_END]
    elif DIRSTATE_V2_REQUIREMENT in _requires(hg_dir):
        log.warning("tool patches: %s requires dirstate-v2 but its dirstate has no docket marker", repo_dir)
        return None
    elif len(header) >= _V1_HEADER:
        node = header[:NODE_LENGTH]
    else:
        log.warning("tool patches: dirstate of %s is empty or truncated", repo_dir)
        return None
    if len(node) != NODE_LENGTH or node == b"\0" * NODE_LENGTH:
        log.warning("tool patches: %s has no checked-out changeset", repo_dir)
        return None
    return node.hex()
