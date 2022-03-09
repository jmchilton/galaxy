from galaxy import model
from galaxy.jobs.manager import JobManager
from galaxy.managers.histories import HistoryManager
from galaxy.model.scoped_session import galaxy_scoped_session
from galaxy.structured_app import MinimalManagerApp
from galaxy.schema.tasks import (
    GenerateHistoryDownload,
    SetupHistoryExportJob,
)
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
