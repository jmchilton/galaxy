#!/usr/bin/env python3
"""Emit changed-path integration CI selection to GITHUB_ENV (stdlib only)."""

import argparse
import json
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "test"))
from integration.integration_selection import (
    classify_paths,
    Selection,
)

SHA = re.compile(r"[0-9a-fA-F]{40}\Z")


def git(*args: str) -> bytes:
    return subprocess.check_output(["git", *args], stderr=subprocess.PIPE)


def event_selection(event_name: str, event: dict[str, Any]) -> Selection:
    try:
        if event_name == "pull_request":
            base = event["pull_request"]["base"]["sha"]
            head = event["pull_request"]["head"]["sha"]
        elif event_name == "push":
            base, head = event["before"], event["after"]
        else:
            return Selection.all(f"{event_name or 'unknown event'} runs the full suite")
        if any(not isinstance(sha, str) or not SHA.fullmatch(sha) or set(sha) == {"0"} for sha in (base, head)):
            return Selection.all("missing or invalid comparison commits")
        # Verify both objects even for push diffs; a missing history must never prune.
        for sha in (base, head):
            git("cat-file", "-e", f"{sha}^{{commit}}")
        if event_name == "pull_request":
            base = git("merge-base", base, head).decode().strip()
        paths = git("diff", "--name-only", "--no-renames", "-z", base, head).decode("utf-8", "surrogateescape")
        changed = [path for path in paths.split("\0") if path]
        selection = classify_paths(changed)
        if not selection.full:
            selection.reason = f"{len(changed)} changed paths; selected expensive families: {', '.join(sorted(selection.families)) or 'none'}"
        return selection
    except (KeyError, TypeError, OSError, subprocess.CalledProcessError):
        return Selection.all("could not determine changed paths")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--event-name", default=os.environ.get("GITHUB_EVENT_NAME", ""))
    parser.add_argument("--event-path", default=os.environ.get("GITHUB_EVENT_PATH"))
    parser.add_argument("--env-file", default=os.environ.get("GITHUB_ENV"))
    args = parser.parse_args()
    try:
        with open(args.event_path) as handle:
            event = json.load(handle)
        selection = event_selection(args.event_name, event)
    except (OSError, TypeError, ValueError):
        selection = Selection.all("event data unavailable")
    print(f"Integration CI: {selection.reason}")
    if args.env_file:
        with open(args.env_file, "a") as handle:
            for name, value in selection.environment().items():
                handle.write(f"{name}={value}\n")


if __name__ == "__main__":
    main()
