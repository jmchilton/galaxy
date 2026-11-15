"""API for asynchronous job running mechanisms can use to fetch or put files
related to running and queued jobs.
"""

import logging
import os
import re
import shutil
import tempfile
from typing import (
    Annotated,
    Optional,
    Union,
)

import anyio
from fastapi import (
    Path,
    Query,
    Request,
)
from sqlalchemy.orm import scoped_session

from galaxy import (
    exceptions,
    util,
)
from galaxy.managers.context import ProvidesAppContext
from galaxy.model import (
    Job,
    JobToOutputDatasetAssociation,
    JobToOutputLibraryDatasetAssociation,
)
from galaxy.security.idencoding import IdEncodingHelper
from galaxy.security.job_files_tokens import (
    JOB_FILES_READ,
    JOB_FILES_WRITE,
    JobFilesScope,
    verify_job_files_token,
)
from galaxy.structured_app import (
    MinimalManagerApp,
    StructuredApp,
)
from galaxy.web import (
    expose_api_anonymous_and_sessionless,
    expose_api_raw_anonymous_and_sessionless,
)
from . import (
    BaseGalaxyAPIController,
    DependsOnApp,
    Router,
)

log = logging.getLogger(__name__)

router = Router(tags=["jobs"])

PUT_STAGING_PREFIX = ".job_files_put_"


class JobFilesAPIController(BaseGalaxyAPIController):
    """This job files controller allows remote job running mechanisms to
    read and modify the current state of files for queued and running jobs.
    It is certainly not meant to represent part of Galaxy's stable, user
    facing API.

    Furthermore, even if a user key corresponds to the user running the job,
    it should not be accepted for authorization - this API allows access to
    low-level unfiltered files and such authorization would break Galaxy's
    security model for tool execution.
    """

    @expose_api_raw_anonymous_and_sessionless
    def index(self, trans: ProvidesAppContext, job_id: str, **kwargs):
        """
        GET /api/jobs/{job_id}/files

        Get a file required to staging a job (proper datasets, extra inputs,
        task-split inputs, working directory files).

        :type   job_id: str
        :param  job_id: encoded id string of the job
        :type   path: str
        :param  path: Path to file.
        :type   job_key: str
        :param  job_key: A key used to authenticate this request as acting on
                         behalf or a job runner for the specified job.
        :type   job_token: str
        :param  job_token: Instead of ``job_key``, a signed token for reading
                           exactly this path (see ``galaxy.security.job_files_tokens``).

        ..note:
            This API method is intended only for consumption by job runners,
            not end users.

        :rtype:     binary
        :returns:   contents of file
        """
        job = self.__authorize_job_access(trans, job_id, JOB_FILES_READ, **kwargs)
        path = kwargs["path"]
        try:
            return open(path, "rb")
        except FileNotFoundError:
            # We know that the job is not terminal, but users (or admin scripts) can purge input datasets.
            # Here we discriminate that case from truly unexpected bugs.
            # Not failing the job here, this is or should be handled by pulsar.
            match = re.match(r"(galaxy_)?dataset_(.*)\.dat", os.path.basename(path))
            if match:
                # This looks like a galaxy dataset, check if any job input has been deleted.
                if any(jtid.dataset.dataset.purged for jtid in job.input_datasets):
                    raise exceptions.ItemDeletionException("Input dataset(s) for job have been purged.")
            else:
                raise

    @expose_api_anonymous_and_sessionless
    def create(self, trans: ProvidesAppContext, job_id: str, payload, **kwargs):
        """
        create( self, trans, job_id, payload, **kwargs )
        * POST /api/jobs/{job_id}/files
            Populate an output file (formal dataset, task split part, working
            directory file (such as those related to metadata)). This should be
            a multipart post with a 'file' parameter containing the contents of
            the actual file to create.

        :type   job_id: str
        :param  job_id: encoded id string of the job
        :type   payload:    dict
        :param  payload:    dictionary structure containing::
            'job_key'   = Key authenticating
            'job_token' = Instead of 'job_key', a signed token for writing exactly 'path'
            'path'      = Path to file to create.

        ..note:
            This API method is intended only for consumption by job runners,
            not end users.

        :rtype:     dict
        :returns:   an okay message
        """
        job = self.__authorize_job_access(trans, job_id, JOB_FILES_WRITE, **payload)
        path = payload.get("path")
        if not path:
            raise exceptions.RequestParameterInvalidException("'path' parameter not provided or empty.")
        self.__check_job_can_write_to_path(trans, job, path)

        # Is this writing an unneeded file? Should this just copy in Python?
        if "__file_path" in payload:
            file_path = payload.get("__file_path")
            upload_store = trans.app.config.nginx_upload_job_files_store
            assert upload_store, (
                "Request appears to have been processed by"
                " nginx_upload_module but Galaxy is not"
                " configured to recognize it"
            )
            assert file_path.startswith(
                upload_store
            ), f"Filename provided by nginx ({file_path}) is not in correct directory ({upload_store})"
            input_file = open(file_path)
        elif "session_id" in payload:
            # code stolen from basic.py
            session_id = payload["session_id"]
            upload_store = (
                trans.app.config.tus_upload_store_job_files
                or trans.app.config.tus_upload_store
                or trans.app.config.new_file_path
            )
            if re.match(r"^[\w-]+$", session_id) is None:
                raise ValueError("Invalid session id format.")
            local_filename = os.path.abspath(os.path.join(upload_store, session_id))
            input_file = open(local_filename)
        else:
            input_file = payload.get("file", payload.get("__file", None)).file
        target_dir = os.path.dirname(path)
        util.safe_makedirs(target_dir)
        try:
            if os.path.exists(path) and (path.endswith("tool_stdout") or path.endswith("tool_stderr")):
                with open(path, "ab") as destination:
                    shutil.copyfileobj(open(input_file.name, "rb"), destination)
            else:
                shutil.move(input_file.name, path)
        finally:
            try:
                input_file.close()
            except OSError:
                # Fails to close file if not using nginx upload because the
                # tempfile has moved and Python wants to delete it.
                pass
        return {"message": "ok"}

    @expose_api_anonymous_and_sessionless
    def tus_patch(self, trans, **kwds):
        """
        Exposed as PATCH /api/job_files/resumable_upload.

        I think based on the docs, a separate tusd server is needed for job files if
        also hosting one for use facing uploads.

        Setting up tusd for job files should just look like (I think):

        tusd -host localhost -port 1080 -upload-dir=<galaxy_root>/database/tmp

        See more discussion of checking upload access, but we shouldn't need the
        API key and session stuff the user upload tusd server should be configured with.

        Also shouldn't need a hooks endpoint for this reason but if you want to add one
        the target CLI entry would be -hooks-http=<galaxy_url>/api/job_files/tus_hooks
        and the action is featured below.

        I would love to check the job state with __authorize_job_access on the first
        POST but it seems like TusMiddleware doesn't default to coming in here for that
        initial POST the way it does for the subsequent PATCHes. Ultimately, the upload
        is still authorized before the write done with POST /api/jobs/<job_id>/files
        so I think there is no route here to mess with user data - the worst of the security
        issues that can be caused is filling up the sever with needless files that aren't
        acted on. Since this endpoint is not meant for public consumption - all the job
        files stuff and the TUS server should be blocked to public IPs anyway and restricted
        to your Pulsar servers and similar targeting could be accomplished with a user account
        and the user facing upload endpoints.
        """
        return None

    @expose_api_anonymous_and_sessionless
    def tus_hooks(self, trans: ProvidesAppContext, **kwds):
        """No-op but if hook specified the way we do for user upload it would hit this action.

        Exposed as PATCH /api/job_files/tus_hooks and documented in the docstring for
        tus_patch.
        """
        pass

    def __authorize_job_access(self, trans: ProvidesAppContext, encoded_job_id: str, scope: JobFilesScope, **kwargs):
        if "path" not in kwargs:
            raise exceptions.ObjectAttributeMissingException("Job files action requires a valid 'path'.")
        if "job_key" not in kwargs and "job_token" not in kwargs:
            raise exceptions.ObjectAttributeMissingException("Job files action requires a valid 'job_key'.")
        return authorize_job_access(
            trans.security,
            trans.sa_session,
            encoded_job_id,
            kwargs.get("job_key"),
            path=kwargs["path"],
            job_token=kwargs.get("job_token"),
            scope=scope,
        )

    def __check_job_can_write_to_path(self, trans: ProvidesAppContext, job: Job, path: str):
        check_job_can_write_to_path(trans.app, job, path)


def authorize_job_access(
    security: IdEncodingHelper,
    sa_session: scoped_session,
    encoded_job_id: str,
    job_key: Optional[str],
    path: Optional[str] = None,
    job_token: Optional[str] = None,
    scope: Optional[JobFilesScope] = None,
) -> Job:
    """Return the job if it is still active and the request is authorized.

    Authorized by ``job_token``, a signed token for ``scope`` access to exactly
    ``path``, when given; otherwise by ``job_key``, the job's job files key.
    """
    job_id = security.decode_id(encoded_job_id)
    if job_token is not None:
        if path is None or scope is None or not verify_job_files_token(security, job_id, path, scope, job_token):
            raise exceptions.ItemAccessibilityException("Invalid or expired job_token supplied.")
    else:
        expected_job_key = security.encode_id(job_id, kind="jobs_files")
        if not util.safe_str_cmp(str(job_key), expected_job_key):
            raise exceptions.ItemAccessibilityException("Invalid job_key supplied.")

    # Verify job is active. Don't update the contents of complete jobs.
    job = sa_session.get(Job, job_id)
    assert job
    if job.state not in Job.non_ready_states:
        error_message = "Attempting to read or modify the files of a job that has already completed."
        raise exceptions.ItemAccessibilityException(error_message)
    return job


def check_job_can_write_to_path(app: MinimalManagerApp, job: Job, path: str) -> None:
    """Verify an idealized job runner should actually be able to write to
    the specified path - it must be a dataset output, a dataset "extra
    file", or a some place in the working directory of this job.

    Would like similar checks for reading the unstructured nature of loc
    files make this very difficult. (See abandoned work here
    https://gist.github.com/jmchilton/9103619.)
    """
    if not _in_working_directory(job, path, app) and not _is_output_dataset_path(job, path):
        raise exceptions.ItemAccessibilityException("Job is not authorized to write to supplied path.")


def _is_output_dataset_path(job: Job, path: str) -> bool:
    """Check if is an output path for this job or a file in the an
    output's extra files path.
    """
    all_output_assocs: list[Union[JobToOutputDatasetAssociation, JobToOutputLibraryDatasetAssociation]] = [
        *job.output_datasets,
        *job.output_library_datasets,
    ]
    for assoc in all_output_assocs:
        dataset = assoc.dataset
        if not dataset:
            continue
        if os.path.abspath(dataset.get_file_name()) == os.path.abspath(path):
            return True
        elif util.in_directory(path, dataset.extra_files_path):
            return True
    return False


def _in_working_directory(job: Job, path: str, app: MinimalManagerApp) -> bool:
    working_directory = app.object_store.get_filename(job, base_dir="job_work", dir_only=True, extra_dir=str(job.id))
    return util.in_directory(path, working_directory)


def _authorize_put(app: StructuredApp, job_id: str, path: str, job_key: Optional[str], job_token: Optional[str]) -> str:
    """Authorize a raw-body write to ``path`` and return the directory to stage it in."""
    if not os.path.isabs(path):
        raise exceptions.RequestParameterInvalidException("'path' must be an absolute path.")
    if job_key is None and job_token is None:
        raise exceptions.ObjectAttributeMissingException("Job files action requires a valid 'job_key'.")
    job = authorize_job_access(
        app.security, app.model.session, job_id, job_key, path=path, job_token=job_token, scope=JOB_FILES_WRITE
    )
    check_job_can_write_to_path(app, job, path)
    target_dir = os.path.dirname(path)
    util.safe_makedirs(target_dir)
    return target_dir


@router.put(
    "/api/jobs/{job_id}/files",
    summary="Write an output or working directory file of a job from the raw request body.",
    description=(
        "For TES servers (Funnel, TESK) that upload task outputs with a plain HTTP PUT. "
        "Authorized by `job_key` like the multipart POST, or by a signed `job_token` for exactly this path; "
        "only for consumption by job runners, "
        "not part of Galaxy's stable, user facing API. The file is replaced, never appended to."
    ),
    public=True,
)
async def put_job_file(
    request: Request,
    job_id: Annotated[str, Path(description="Encoded id string of the job.")],
    path: Annotated[str, Query(description="Absolute path of the file to write.")],
    job_key: Annotated[Optional[str], Query(description="The job's job files key.")] = None,
    job_token: Annotated[
        Optional[str], Query(description="Instead of `job_key`, a signed token for writing exactly `path`.")
    ] = None,
    app: StructuredApp = DependsOnApp,
) -> dict[str, str]:
    # Authorize before reading the body, then stage it next to the target and rename it into place.
    target_dir = await anyio.to_thread.run_sync(_authorize_put, app, job_id, path, job_key, job_token)
    fd, staging_path = tempfile.mkstemp(prefix=PUT_STAGING_PREFIX, dir=target_dir)
    try:
        with os.fdopen(fd, "wb") as staging_file:
            async for chunk in request.stream():
                staging_file.write(chunk)
        os.replace(staging_path, path)
    except BaseException:
        try:
            os.unlink(staging_path)
        except OSError:
            pass
        raise
    return {"message": "ok"}
