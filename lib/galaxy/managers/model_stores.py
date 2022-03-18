import base64
import json
import os
from tempfile import (
    mkdtemp,
    NamedTemporaryFile,
)
from typing import Optional

from galaxy import model
from galaxy.exceptions import RequestParameterInvalidException
from galaxy.jobs.manager import JobManager
from galaxy.managers.histories import HistoryManager
from galaxy.model.scoped_session import galaxy_scoped_session
from galaxy.model.store import (
    get_import_model_store_for_dict,
    get_import_model_store_for_directory,
    ImportDiscardedDataType,
    ImportOptions,
    ObjectImportTracker,
)
from galaxy.schema.schema import HistoryContentType
from galaxy.schema.tasks import (
    GenerateHistoryContentDownload,
    GenerateHistoryDownload,
    GenerateInvocationDownload,
    ImportModelStoreTaskRequest,
    SetupHistoryExportJob,
)
from galaxy.structured_app import MinimalManagerApp
from galaxy.util.compression_utils import CompressedFile
from galaxy.web.short_term_storage import (
    ShortTermStorageMonitor,
    storage_context,
)


class ModelStoreManager:
    def __init__(
        self,
        app: MinimalManagerApp,
        history_manager: HistoryManager,
        sa_session: galaxy_scoped_session,
        job_manager: JobManager,
        short_term_storage_monitor: ShortTermStorageMonitor,
    ):
        self._app = app
        self._sa_session = sa_session
        self._job_manager = job_manager
        self._history_manager = history_manager
        self._short_term_storage_monitor = short_term_storage_monitor

    def setup_history_export_job(self, request: SetupHistoryExportJob):
        history_id = request.history_id
        job_id = request.job_id
        include_hidden = request.include_hidden
        include_deleted = request.include_deleted
        store_directory = request.store_directory

        history = self._sa_session.query(model.History).get(history_id)
        # symlink files on export, on worker files will tarred up in a dereferenced manner.
        with model.store.DirectoryModelExportStore(
            store_directory, app=self._app, export_files="symlink"
        ) as export_store:
            export_store.export_history(history, include_hidden=include_hidden, include_deleted=include_deleted)
        job = self._sa_session.query(model.Job).get(job_id)
        job.state = model.Job.states.NEW
        self._sa_session.flush()
        self._job_manager.enqueue(job)

    def prepare_history_download(self, request: GenerateHistoryDownload):
        model_store_format = request.model_store_format
        history = self._history_manager.by_id(request.history_id)
        export_files = "symlink" if request.include_files else None
        include_hidden = request.include_hidden
        include_deleted = request.include_deleted
        with storage_context(
            request.short_term_storage_request_id, self._short_term_storage_monitor
        ) as short_term_storage_target:
            with model.store.get_export_store_factory(self._app, model_store_format, export_files=export_files)(
                short_term_storage_target.path
            ) as export_store:
                export_store.export_history(history, include_hidden=include_hidden, include_deleted=include_deleted)

    def prepare_history_content_download(self, request: GenerateHistoryContentDownload):
        model_store_format = request.model_store_format
        export_files = "symlink" if request.include_files else None
        with storage_context(
            request.short_term_storage_request_id, self._short_term_storage_monitor
        ) as short_term_storage_target:
            with model.store.get_export_store_factory(self._app, model_store_format, export_files=export_files)(
                short_term_storage_target.path
            ) as export_store:
                if request.content_type == HistoryContentType.dataset:
                    hda = self._sa_session.query(model.HistoryDatasetAssociation).get(request.content_id)
                    export_store.add_dataset(hda)
                else:
                    hdca = self._sa_session.query(model.HistoryDatasetCollectionAssociation).get(request.content_id)
                    export_store.export_collection(hdca)

    def prepare_invocation_download(self, request: GenerateInvocationDownload):
        model_store_format = request.model_store_format
        export_files = "symlink" if request.include_files else None
        with storage_context(
            request.short_term_storage_request_id, self._short_term_storage_monitor
        ) as short_term_storage_target:
            with model.store.get_export_store_factory(self._app, model_store_format, export_files=export_files)(
                short_term_storage_target.path
            ) as export_store:
                invocation = self._sa_session.query(model.WorkflowInvocation).get(request.invocation_id)
                export_store.export_workflow_invocation(invocation)

    def import_model_store(self, request: ImportModelStoreTaskRequest):
        import_options = ImportOptions(
            discarded_data=ImportDiscardedDataType.FORCE,
            allow_library_creation=request.for_library,
        )
        history_id = request.history_id
        if history_id:
            history = self._sa_session.query(model.History).get(history_id)
        else:
            history = None
        user_id = request.user.user_id
        if user_id:
            galaxy_user = self._sa_session.query(model.User).get(user_id)
        else:
            galaxy_user = None
        model_import_store = source_uri_to_import_store(
            request.source_uri,
            self._app,
            galaxy_user,
            import_options,
        )
        new_history = history is None and not request.for_library
        if new_history:
            if not model_import_store.defines_new_history():
                raise RequestParameterInvalidException("Supplied model store doesn't define new history to import.")
            with model_import_store.target_history(legacy_history_naming=False) as new_history:
                object_tracker = model_import_store.perform_import(new_history, new_history=True)
                object_tracker.new_history = new_history
        else:
            object_tracker = model_import_store.perform_import(
                history=history,
                new_history=new_history,
            )
        return object_tracker


def source_uri_to_import_store(
    source_uri,
    app,
    galaxy_user,
    import_options,
):
    # TODO: Move this into galaxy.model.store.
    # TODO: handle non file:// URIs.
    if source_uri.endswith(".json"):
        if source_uri.startswith("file://"):
            target_path = source_uri[len("file://") :]
        else:
            target_path = source_uri
        with open(target_path, "r") as f:
            store_dict = json.load(f)
        assert isinstance(store_dict, dict)
        model_import_store = get_import_model_store_for_dict(
            store_dict,
            import_options=import_options,
            app=app,
            user=galaxy_user,
        )
    else:
        target_dir = source_uri[len("file://") :]
        assert os.path.isdir(source_uri)
        model_import_store = get_import_model_store_for_directory(
            target_dir, import_options=import_options, app=app, user=galaxy_user
        )
    return model_import_store


def payload_to_source_uri(payload) -> str:
    if payload.store_content_base64:
        source_content = payload.store_content_base64
        assert source_content
        tf = NamedTemporaryFile("wb")
        tf.write(base64.b64decode(source_content))
        tf.flush()
        temp_dir = mkdtemp()
        target_dir = os.path.abspath(CompressedFile(tf.name).extract(temp_dir))
        source_uri = f"file://{target_dir}"
    else:
        store_dict = payload.store_dict
        assert isinstance(store_dict, dict)
        temp_dir = mkdtemp()
        import_json = os.path.join(temp_dir, "import_store.json")
        with open(import_json, "w") as f:
            json.dump(store_dict, f)
        source_uri = f"file://{import_json}"
    return source_uri


def create_objects_from_store(
    app: MinimalManagerApp,
    galaxy_user: Optional[model.User],
    payload,
    history: Optional[model.History] = None,
    for_library: bool = False,
) -> ObjectImportTracker:
    import_options = ImportOptions(
        discarded_data=ImportDiscardedDataType.FORCE,
        allow_library_creation=for_library,
    )
    if payload.store_content_base64:
        source_content = payload.store_content_base64
        assert source_content
        tf = NamedTemporaryFile("wb")
        tf.write(base64.b64decode(source_content))
        tf.flush()
        temp_dir = mkdtemp()
        target_dir = CompressedFile(tf.name).extract(temp_dir)
        model_import_store = get_import_model_store_for_directory(
            target_dir, import_options=import_options, app=app, user=galaxy_user
        )
    else:
        store_dict = payload.store_dict
        assert isinstance(store_dict, dict)
        model_import_store = get_import_model_store_for_dict(
            store_dict,
            import_options=import_options,
            app=app,
            user=galaxy_user,
        )

    new_history = history is None and not for_library
    if new_history:
        if not model_import_store.defines_new_history():
            raise RequestParameterInvalidException("Supplied model store doesn't define new history to import.")
        with model_import_store.target_history(legacy_history_naming=False) as new_history:
            object_tracker = model_import_store.perform_import(new_history, new_history=True)
            object_tracker.new_history = new_history
    else:
        object_tracker = model_import_store.perform_import(
            history=history,
            new_history=new_history,
        )
    return object_tracker
