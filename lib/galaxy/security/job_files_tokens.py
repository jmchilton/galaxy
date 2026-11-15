"""Signed, expiring tokens that authorize one job files API call on one path.

A job's ``job_key`` opens every readable path of the job, for reading and
writing, until the job ends. Runners that hand file URLs to a third party (a TES
server stores and logs them) can sign each URL instead: the token is bound to
the job, the exact ``path`` string, the direction (read or write) and an expiry
time. The job files API still checks the job's state and its write locations.

A token is ``<expires>.<signature>``: the expiry as Unix seconds and an
unpadded base64url HMAC-SHA256 over the job id, direction, expiry and path. The
key is derived from Galaxy's ``id_secret``, so tokens survive restarts and
are only valid on the Galaxy that issued them.
"""

import base64
import hashlib
import hmac
import time
from typing import (
    Literal,
    Optional,
)

from galaxy.security.idencoding import IdEncodingHelper
from galaxy.util import smart_str

JobFilesScope = Literal["r", "w"]
JOB_FILES_READ: JobFilesScope = "r"
"""GET and HEAD."""
JOB_FILES_WRITE: JobFilesScope = "w"
"""POST and PUT."""

_SCOPES = (JOB_FILES_READ, JOB_FILES_WRITE)
_KEY_PURPOSE = b"galaxy job files token v1"


def job_files_token(security: IdEncodingHelper, job_id: int, path: str, scope: JobFilesScope, expires: int) -> str:
    """A token authorizing ``scope`` access to ``path`` of job ``job_id`` until ``expires`` (Unix seconds)."""
    if scope not in _SCOPES:
        raise ValueError(f"Unknown job files token scope {scope!r}")
    return f"{int(expires)}.{_signature(security, job_id, path, scope, int(expires))}"


def verify_job_files_token(
    security: IdEncodingHelper,
    job_id: int,
    path: str,
    scope: JobFilesScope,
    token: str,
    now: Optional[float] = None,
) -> bool:
    """Whether ``token`` authorizes ``scope`` access to exactly ``path`` of job ``job_id`` at ``now``."""
    expires_text, _, signature = str(token).partition(".")
    if not (expires_text.isascii() and expires_text.isdigit()) or not signature or scope not in _SCOPES:
        return False
    expires = int(expires_text)
    if (time.time() if now is None else now) > expires:
        return False
    expected = _signature(security, job_id, path, scope, expires)
    return hmac.compare_digest(smart_str(signature), smart_str(expected))


def _signature(security: IdEncodingHelper, job_id: int, path: str, scope: str, expires: int) -> str:
    key = hmac.new(smart_str(security.id_secret), _KEY_PURPOSE, hashlib.sha256).digest()
    message = b"\0".join(smart_str(part) for part in (str(int(job_id)), scope, str(expires), path))
    digest = hmac.new(key, message, hashlib.sha256).digest()
    return base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")
