"""Locate files that tool help references by paths relative to the tool."""

import mimetypes
import os

from galaxy.util.path import safe_contains

STATIC_IMAGES = "static/images"
# SVG can carry script, which would run on Galaxy's origin if the image were opened directly.
UNSERVED_IMAGE_TYPES = {"image/svg+xml"}


def find_tool_asset(base_dir: str, asset_path: str) -> str | None:
    """Find ``asset_path`` under ``base_dir``, trying ``static/images/`` first as Tool Shed help does."""
    # safe_contains resolves symlinks in the candidate, so compare against the resolved base.
    base_dir = os.path.realpath(base_dir)
    candidates = []
    if STATIC_IMAGES not in asset_path:
        candidates.append(os.path.join(base_dir, STATIC_IMAGES, asset_path))
    candidates.append(os.path.join(base_dir, asset_path))
    for candidate in candidates:
        candidate = os.path.abspath(candidate)
        if safe_contains(base_dir, candidate) and os.path.isfile(candidate):
            return candidate
    return None


def help_image_media_type(path: str) -> str | None:
    """Media type to serve ``path`` as a help image, or ``None`` if it isn't a servable image."""
    media_type, _ = mimetypes.guess_type(path)
    if media_type and media_type.startswith("image/") and media_type not in UNSERVED_IMAGE_TYPES:
        return media_type
    return None
