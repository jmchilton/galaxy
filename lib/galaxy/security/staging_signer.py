"""Signatures for URLs that let a remote job runner stage a job's files.

A signature binds one transfer: a job, the kind and id of the object being
staged, a path within that object (empty for the object itself) and an expiry.
A URL carrying it authorizes exactly that transfer, so a job holding the URL
cannot alter it to reach any other object.
"""

import hashlib
import hmac
import time
from typing import Literal

from galaxy.security.idencoding import IdEncodingHelper
from galaxy.util import smart_str

# Derive the signing key from id_secret with a purpose label, so signatures here
# never coincide with any other use of id_secret.
KEY_PURPOSE = b"galaxy-job-staging-v1"

StagedInputKind = Literal["dataset", "metadata_file"]

INPUT_ROUTE = "/api/jobs/{job_id}/staging/inputs/{kind}/{object_id}"

# The staging URLs a runner receives must outlive the job's wait in a queue; the
# job leaving Job.non_ready_states ends them sooner.
INPUT_URL_LIFETIME_SECONDS = 7 * 24 * 60 * 60


class StagingUrlSigner:
    def __init__(self, id_secret: str) -> None:
        self._key = hmac.new(smart_str(id_secret), KEY_PURPOSE, hashlib.sha256).digest()

    def sign(self, job_id: int, kind: str, object_id: int, path: str, expires: int) -> str:
        message = f"v1|{job_id}|{kind}|{object_id}|{path}|{expires}"
        return hmac.new(self._key, message.encode("utf-8"), hashlib.sha256).hexdigest()

    def verify(
        self,
        job_id: int,
        kind: str,
        object_id: int,
        path: str,
        expires: int,
        signature: str,
        now: float | None = None,
    ) -> bool:
        if (time.time() if now is None else now) >= expires:
            return False
        expected = self.sign(job_id, kind, object_id, path, expires)
        # Compare bytes: compare_digest rejects non-ASCII str, and signatures arrive from URLs.
        return hmac.compare_digest(expected.encode("utf-8"), signature.encode("utf-8"))


def input_url(
    security: IdEncodingHelper,
    galaxy_url: str,
    job_id: int,
    kind: StagedInputKind,
    object_id: int,
    expires: int,
    redirect: bool = False,
) -> str:
    """A signed URL for one input of a job, answered by ``JobObjectStagingManager.staged_input``.

    With ``redirect``, the runner may be sent to a presigned object store URL; only ask for that when
    the runner can reach the store and follows redirects. The flag is not signed: it only changes how
    the job receives its own input.
    """
    signature = StagingUrlSigner(security.id_secret).sign(job_id, kind, object_id, "", expires)
    encoded_job_id = security.encode_id(job_id)
    encoded_object_id = security.encode_id(object_id)
    route = INPUT_ROUTE.format(job_id=encoded_job_id, kind=kind, object_id=encoded_object_id)
    url = f"{galaxy_url}{route}?exp={expires}&sig={signature}"
    return f"{url}&redirect=1" if redirect else url
