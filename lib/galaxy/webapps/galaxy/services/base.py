import base64
from tempfile import (
    mkdtemp,
    NamedTemporaryFile,
)
from typing import (
    Any,
    cast,
    List,
    NamedTuple,
    Optional,
    Type,
)

from celery.result import AsyncResult

from galaxy.exceptions import (
    AuthenticationRequired,
    ConfigDoesNotAllowException,
    RequestParameterInvalidException,
)
from galaxy.managers.base import (
    decode_with_security,
    encode_with_security,
    get_class,
    get_object,
    SortableManager,
)
from galaxy.managers.context import ProvidesUserContext
from galaxy.model import User
from galaxy.model.store import (
    BagArchiveModelExportStore,
    get_import_model_store_for_dict,
    get_import_model_store_for_directory,
    ImportOptions,
    ModelExportStore,
    TarModelExportStore,
)
from galaxy.schema.fields import EncodedDatabaseIdField
from galaxy.schema.schema import AsyncTaskResultSummary
from galaxy.security.idencoding import IdEncodingHelper
from galaxy.util.compression_utils import CompressedFile


def ensure_celery_tasks_enabled(config):
    if not config.enable_celery_tasks:
        raise ConfigDoesNotAllowException(
            "This operation requires asynchronous tasks to be enabled on the Galaxy server and they are not, please contact the server admin."
        )


class ServiceBase:
    """Base class with common logic and utils reused by other services.

    A service class:
     - Provides top level operations (`Index`, `Show`, `Delete`...) that are usually
       consumed directly by the API controllers or other services.
     - Uses a combination of managers to perform the operations and
       avoids accessing the database layer directly.
     - Can speak 'pydantic' and has rich type annotations to be explicit about
       the required parameters and outputs of each operation.
    """

    def __init__(self, security: IdEncodingHelper):
        self.security = security

    def decode_id(self, id: EncodedDatabaseIdField) -> int:
        """Decodes a previously encoded database ID."""
        return decode_with_security(self.security, id)

    def encode_id(self, id: int) -> EncodedDatabaseIdField:
        """Encodes a raw database ID."""
        return encode_with_security(self.security, id)

    def decode_ids(self, ids: List[EncodedDatabaseIdField]) -> List[int]:
        """
        Decodes all encoded IDs in the given list.
        """
        return [self.decode_id(id) for id in ids]

    def encode_all_ids(self, rval, recursive: bool = False):
        """
        Encodes all integer values in the dict rval whose keys are 'id' or end with '_id'

        It might be useful to turn this in to a decorator
        """
        return self.security.encode_all_ids(rval, recursive=recursive)

    def build_order_by(self, manager: SortableManager, order_by_query: Optional[str] = None):
        """Returns an ORM compatible order_by clause using the order attribute and the given manager.

        The manager has to implement the `parse_order_by` function to support all the sortable model attributes."""
        ORDER_BY_SEP_CHAR = ","
        if order_by_query and ORDER_BY_SEP_CHAR in order_by_query:
            return [manager.parse_order_by(o) for o in order_by_query.split(ORDER_BY_SEP_CHAR)]
        return manager.parse_order_by(order_by_query)

    def get_class(self, class_name):
        """
        Returns the class object that a string denotes. Without this method, we'd have to do eval(<class_name>).
        """
        return get_class(class_name)

    def get_object(self, trans, id, class_name, check_ownership=False, check_accessible=False, deleted=None):
        """
        Convenience method to get a model object with the specified checks.
        """
        return get_object(
            trans, id, class_name, check_ownership=check_ownership, check_accessible=check_accessible, deleted=deleted
        )

    def check_user_is_authenticated(self, trans: ProvidesUserContext):
        """Raises an exception if the request is anonymous."""
        if trans.anonymous:
            raise AuthenticationRequired("API authentication required for this request")

    def get_authenticated_user(self, trans: ProvidesUserContext) -> User:
        """Gets the authenticated user and prevents access from anonymous users."""
        self.check_user_is_authenticated(trans)
        return cast(User, trans.user)


class ServedExportStore(NamedTuple):
    export_store: ModelExportStore
    export_target: Any


class ServesExportStores:
    def serve_export_store(self, app, download_format: str):
        export_store_class: Type[ModelExportStore]
        export_store_class_kwds = {
            "app": app,
            "export_files": None,
            "serialize_dataset_objects": False,
        }
        export_target = NamedTemporaryFile("wb")
        if download_format in ["tar.gz", "tgz"]:
            export_store_class = TarModelExportStore
            export_store_class_kwds["gzip"] = True
        elif download_format.startswith("bag."):
            bag_archiver = download_format[len("bag.") :]
            if bag_archiver not in ["zip", "tar", "tgz"]:
                raise RequestParameterInvalidException(f"Unknown download format [{download_format}]")
            export_store_class = BagArchiveModelExportStore
            export_store_class_kwds["bag_archiver"] = bag_archiver
        else:
            raise RequestParameterInvalidException(f"Unknown download format [{download_format}]")
        export_store = export_store_class(export_target.name, **export_store_class_kwds)
        return ServedExportStore(export_store, export_target)


class ConsumesModelStores:
    def create_objects_from_store(
        self,
        trans,
        payload,
        history=None,
        for_library=False,
    ):
        import_options = ImportOptions(
            allow_library_creation=for_library,
        )
        galaxy_user = None
        if isinstance(trans.user, User):
            galaxy_user = trans.user
        if payload.store_content_base64:
            source_content = payload.store_content_base64
            assert source_content
            tf = NamedTemporaryFile("wb")
            tf.write(base64.b64decode(source_content))
            tf.flush()
            temp_dir = mkdtemp()
            target_dir = CompressedFile(tf.name).extract(temp_dir)
            model_import_store = get_import_model_store_for_directory(
                target_dir, import_options=import_options, app=trans.app, user=galaxy_user
            )
        else:
            store_dict = payload.store_dict
            assert isinstance(store_dict, dict)
            model_import_store = get_import_model_store_for_dict(
                store_dict,
                import_options=import_options,
                app=trans.app,
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


def async_task_summary(async_result: AsyncResult) -> AsyncTaskResultSummary:
    return AsyncTaskResultSummary(
        id=async_result.id,
        ignored=async_result.ignored,
        name=async_result.name,
        queue=async_result.queue,
    )
