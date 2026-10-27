"""Serve a running job's inputs to a remote job runner from the object store.

Galaxy gives a remote runner (Pulsar) one signed URL per input
(``galaxy.security.staging_signer.input_url``) instead of a path on its own disk.
A request for such a URL is answered from the object store by identity (``staged_input``): with a redirect to a presigned URL
when the URL asks for one and the store can issue it, else with a stream read
straight from the store, else from a local file (disk stores).
Nothing here needs a filesystem shared between Galaxy hosts.
"""

import logging
from dataclasses import dataclass
from typing import Any

from galaxy import exceptions
from galaxy.managers.job_files import (
    get_active_job,
    INPUTS_PURGED_MESSAGE,
)
from galaxy.model import (
    Dataset,
    Job,
    MetadataFile,
)
from galaxy.model.scoped_session import galaxy_scoped_session
from galaxy.objectstore import (
    BaseObjectStore,
    DataStream,
)
from galaxy.security.idencoding import IdEncodingHelper
from galaxy.security.staging_signer import (
    StagedInputKind,
    StagingUrlSigner,
)

log = logging.getLogger(__name__)

# A presigned URL Galaxy redirects to outlives the job, as Galaxy cannot revoke it.
# The runner follows it at once and comes back to the staging URL to resume or
# retry, so it need only last one request, with a margin for clock skew between
# Galaxy and the store.
REDIRECT_URL_LIFETIME_SECONDS = 15 * 60


@dataclass
class StagedInput:
    """How to answer a staging request: exactly one of the transfer fields is set, none for HEAD."""

    size: int
    redirect_url: str | None = None
    stream: DataStream | None = None
    path: str | None = None


class JobObjectStagingManager:
    def __init__(
        self, sa_session: galaxy_scoped_session, object_store: BaseObjectStore, security: IdEncodingHelper
    ) -> None:
        self._sa_session = sa_session
        self._object_store = object_store
        self._signer = StagingUrlSigner(security.id_secret)

    def staged_input(
        self,
        job_id: int,
        kind: StagedInputKind,
        object_id: int,
        expires: int,
        signature: str,
        head: bool = False,
        redirect: bool = False,
    ) -> StagedInput:
        if not self._signer.verify(job_id, kind, object_id, "", expires, signature):
            raise exceptions.ItemAccessibilityException("Invalid or expired staging URL.")
        job = get_active_job(self._sa_session, job_id)
        obj, dataset, path_kwargs = self._input_object(job, kind, object_id)
        if dataset.purged:
            raise exceptions.ItemDeletionException(INPUTS_PURGED_MESSAGE)

        size = self._object_store.size(obj, **path_kwargs)
        if head:
            return StagedInput(size=size)
        if redirect and (
            redirect_url := self._object_store.get_direct_download_url(
                obj, expires_in=REDIRECT_URL_LIFETIME_SECONDS, **path_kwargs
            )
        ):
            return StagedInput(size=size, redirect_url=redirect_url)
        if (stream := self._object_store.get_data_stream(obj, write_cache=False, **path_kwargs)) is not None:
            return StagedInput(size=size, stream=stream)
        return StagedInput(size=size, path=self._object_store.get_filename(obj, **path_kwargs))

    def _input_object(
        self, job: Job, kind: StagedInputKind, object_id: int
    ) -> tuple[Dataset | MetadataFile, Dataset, dict[str, Any]]:
        """The object to read, the dataset it belongs to, and where it sits in that dataset's store."""
        input_associations = [
            *(assoc.dataset for assoc in job.input_datasets),
            *(assoc.dataset for assoc in job.input_library_datasets),
        ]
        if kind == "dataset":
            for association in input_associations:
                dataset = association.dataset if association is not None else None
                if dataset is not None and dataset.id == object_id:
                    return dataset, dataset, {}
        elif kind == "metadata_file":
            metadata_file = self._sa_session.get(MetadataFile, object_id)
            if metadata_file is not None:
                owner = metadata_file.history_dataset or metadata_file.library_dataset
                if owner is not None and owner.dataset is not None and owner in input_associations:
                    return metadata_file, owner.dataset, metadata_file.object_store_path_kwargs()
        raise exceptions.ItemAccessibilityException(f"Requested {kind} is not an input of this job.")
