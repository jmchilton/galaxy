from functools import wraps

from celery import shared_task
from kombu import serialization
from sqlalchemy.orm.scoping import (
    scoped_session,
)

from galaxy import model
from galaxy.config import GalaxyAppConfiguration
from galaxy.managers.collections import DatasetCollectionManager
from galaxy.managers.hdas import HDAManager
from galaxy.managers.lddas import LDDAManager
from galaxy.managers.markdown_util import generate_branded_pdf
from galaxy.managers.model_stores import ModelStoreManager
from galaxy.schema.tasks import (
    GenerateHistoryContentDownload,
    GenerateHistoryDownload,
    GenerateInvocationDownload,
    GeneratePdfDownload,
    MaterializeDatasetInstanceTaskRequest,
    PrepareDatasetCollectionDownload,
    SetupHistoryExportJob,
)
from galaxy.util import ExecutionTimer
from galaxy.util.custom_logging import get_logger
from galaxy.web.short_term_storage import ShortTermStorageMonitor
from . import get_galaxy_app
from ._serialization import schema_dumps, schema_loads

log = get_logger(__name__)
PYDANTIC_AWARE_SERIALIER_NAME = 'pydantic-aware-json'


serialization.register(
    PYDANTIC_AWARE_SERIALIER_NAME,
    encoder=schema_dumps,
    decoder=schema_loads,
    content_type='application/json'
)


def galaxy_task(*args, action=None, **celery_task_kwd):
    if 'serializer' not in celery_task_kwd:
        celery_task_kwd['serializer'] = PYDANTIC_AWARE_SERIALIER_NAME

    def decorate(func):

        @shared_task(**celery_task_kwd)
        @wraps(func)
        def wrapper(*args, **kwds):
            app = get_galaxy_app()
            assert app
            desc = func.__name__
            if action is not None:
                desc += f" to {action}"
            timer = ExecutionTimer()
            try:
                rval = app.magic_partial(func)(*args, **kwds)
                message = f"Successfully executed Celery task {desc} {timer}"
                log.info(message)
                return rval
            except Exception:
                log.warning(f"Celery task execution failed for {desc} {timer}")
                raise

        return wrapper

    if len(args) == 1 and callable(args[0]):
        return decorate(args[0])
    else:
        return decorate


@galaxy_task(ignore_result=True, action="recalcuate a user's disk usage")
def recalculate_user_disk_usage(session: scoped_session, user_id=None):
    if user_id:
        user = session.query(model.User).get(user_id)
        if user:
            user.calculate_and_set_disk_usage()
            log.info(f"New user disk usage is {user.disk_usage}")
        else:
            log.error(f"Recalculate user disk usage task failed, user {user_id} not found")
    else:
        log.error("Recalculate user disk usage task received without user_id.")


@galaxy_task(ignore_result=True, action="purge a history dataset")
def purge_hda(hda_manager: HDAManager, hda_id):
    hda = hda_manager.by_id(hda_id)
    hda_manager._purge(hda)


@galaxy_task(ignore_result=True)
def materialize(
    hda_manager: HDAManager,
    request: MaterializeDatasetInstanceTaskRequest,
):
    """Materialize datasets using HDAManager."""
    hda_manager.materialize(request)


@galaxy_task(action="set dataset association metadata")
def set_metadata(hda_manager: HDAManager, ldda_manager: LDDAManager, dataset_id, model_class='HistoryDatasetAssociation'):
    if model_class == 'HistoryDatasetAssociation':
        dataset = hda_manager.by_id(dataset_id)
    elif model_class == 'LibraryDatasetDatasetAssociation':
        dataset = ldda_manager.by_id(dataset_id)
    dataset.datatype.set_meta(dataset)


@galaxy_task(ignore_result=True, action="setup and queue a history export job")
def export_history(
    model_store_manager: ModelStoreManager,
    request: SetupHistoryExportJob,
):
    model_store_manager.setup_history_export_job(request)


@galaxy_task(action="stage a dataset collection zip for download")
def prepare_dataset_collection_download(
    request: PrepareDatasetCollectionDownload,
    collection_manager: DatasetCollectionManager,
):
    collection_manager.write_dataset_collection(request)


@galaxy_task(action="generate and stage a PDF for download")
def prepare_pdf_download(
    request: GeneratePdfDownload,
    config: GalaxyAppConfiguration,
    short_term_storage_monitor: ShortTermStorageMonitor
):
    generate_branded_pdf(request, config, short_term_storage_monitor)


@galaxy_task(action="generate and stage a history model store for download")
def prepare_history_download(
    model_store_manager: ModelStoreManager,
    request: GenerateHistoryDownload,
):
    model_store_manager.prepare_history_download(request)


@galaxy_task(action="generate and stage a history content model store for download")
def prepare_history_content_download(
    model_store_manager: ModelStoreManager,
    request: GenerateHistoryContentDownload,
):
    model_store_manager.prepare_history_content_download(request)


@galaxy_task(action="generate and stage a workflow invocation store for download")
def prepare_invocation_download(
    model_store_manager: ModelStoreManager,
    request: GenerateInvocationDownload,
):
    model_store_manager.prepare_invocation_download(request)


@galaxy_task(action="cleanup the history audit table")
def prune_history_audit_table(sa_session: scoped_session):
    """Prune ever growing history_audit table."""
    model.HistoryAudit.prune(sa_session)


@galaxy_task(action="cleanup short term storage files")
def cleanup_short_term_storage(storage_monitor: ShortTermStorageMonitor):
    """Cleanup short term storage."""
    storage_monitor.cleanup()
