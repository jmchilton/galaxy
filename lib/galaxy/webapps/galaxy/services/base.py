import mimetypes
from tempfile import NamedTemporaryFile
from typing import (
    Any,
    cast,
    NamedTuple,
    Optional,
)

from galaxy.exceptions import (
    AuthenticationRequired,
    ConfigDoesNotAllowException,
)
from galaxy.managers.base import (
    decode_with_security,
    encode_with_security,
    get_class,
    get_object,
    SortableManager,
)
from galaxy.managers.context import ProvidesUserContext
from galaxy.managers.model_stores import create_objects_from_store
from galaxy.model import (
    ToolExecutionState,
    ToolRequest,
    User,
)
from galaxy.model.store import (
    get_export_store_factory,
    ModelExportStore,
)
from galaxy.schema.fields import EncodedDatabaseIdField
from galaxy.schema.schema import (
    TOOL_EXECUTION_STATE_ENCODE_KIND,
    ToolExecutionModel,
    ToolRequestDetailedModel,
    ToolRequestModel,
)
from galaxy.security.idencoding import IdEncodingHelper
from galaxy.short_term_storage import (
    ShortTermStorageAllocator,
    ShortTermStorageTarget,
)
from galaxy.tool_util.parameters import (
    encode as encode_request,
    input_models_for_tool_source,
)
from galaxy.tool_util.parameters.state import RequestInternalToolState
from galaxy.tool_util.parser import get_tool_source
from galaxy.util import ready_name_for_url


def ensure_celery_tasks_enabled(config):
    if not config.enable_celery_tasks:
        raise ConfigDoesNotAllowException(
            "This operation requires asynchronous tasks to be enabled on the Galaxy server and they are not, please contact the server admin."
        )


class SecurityNotProvidedError(Exception):
    pass


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

    def __init__(self, security: Optional[IdEncodingHelper] = None):
        self._security = security

    @property
    def security(self) -> IdEncodingHelper:
        if self._security is None:
            raise SecurityNotProvidedError(
                "Security encoding helper must be set in the service constructor to encode/decode ids."
            )
        return self._security

    def decode_id(self, id: EncodedDatabaseIdField, kind: Optional[str] = None) -> int:
        """Decodes a previously encoded database ID."""
        return decode_with_security(self.security, id, kind=kind)

    def encode_id(self, id: int, kind: Optional[str] = None) -> EncodedDatabaseIdField:
        """Encodes a raw database ID."""
        return encode_with_security(self.security, id, kind=kind)

    def decode_ids(self, ids: list[EncodedDatabaseIdField]) -> list[int]:
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


def model_store_storage_target(
    short_term_storage_allocator: ShortTermStorageAllocator, file_name: str, model_store_format: str
) -> ShortTermStorageTarget:
    cleaned_filename = ready_name_for_url(file_name)
    filename_with_extension = f"{cleaned_filename}.{model_store_format}"
    mime_type = mimetypes.guess_type(filename_with_extension)[0] or "application/octet-stream"

    return short_term_storage_allocator.new_target(
        filename_with_extension,
        mime_type,
    )


class ServesExportStores:
    def serve_export_store(self, app, download_format: str):
        export_target = NamedTemporaryFile("wb")
        export_store = get_export_store_factory(app, download_format)(export_target.name)
        return ServedExportStore(export_store, export_target)


class ConsumesModelStores:
    def create_objects_from_store(
        self,
        trans,
        payload,
        history=None,
        for_library=False,
    ):
        galaxy_user = None
        if isinstance(trans.user, User):
            galaxy_user = trans.user
        return create_objects_from_store(
            app=trans.app,
            galaxy_user=galaxy_user,
            payload=payload,
            history=history,
            for_library=for_library,
        )


def _encode_request_payload(payload: dict, parsed_tool_source, security: IdEncodingHelper) -> dict[str, Any]:
    """Encode HDA/HDCA ids in a request_internal payload using strongly-typed
    parameter walking. ``parsed_tool_source`` is a tool-parser instance (the
    parameter bundle is derived from it)."""
    parameter_bundle = input_models_for_tool_source(parsed_tool_source)
    internal_state = RequestInternalToolState(payload or {})
    encoded_state = encode_request(internal_state, parameter_bundle, security.encode_id)
    return encoded_state.input_state


def _parsed_tool_source_from_row(tool_source_model) -> Any:
    """Parse a persisted ``ToolSource`` row into a tool-parser instance."""
    raw_tool_source = cast(str, tool_source_model.source)
    return get_tool_source(
        tool_source_class=tool_source_model.source_class,
        raw_tool_source=raw_tool_source,
    )


def _tool_request_payload_or_empty(tool_request: ToolRequest) -> dict:
    """Tolerant payload read for serialization: legacy NULL-request rows
    (preserved by the migration's defensive guard) have no TES and yield
    {}. The strict resolver path uses tool_request_payload() which
    raises on missing TES."""
    tes = tool_request.tool_execution_state
    if tes is None or not isinstance(tes.request, dict):
        return {}
    return tes.request


def tool_request_to_model(tool_request: ToolRequest, security: IdEncodingHelper) -> ToolRequestModel:
    parsed = _parsed_tool_source_from_row(tool_request.tool_execution_state.tool_source)
    encoded_request = _encode_request_payload(_tool_request_payload_or_empty(tool_request), parsed, security)
    as_dict = {
        "id": tool_request.id,
        "request": encoded_request,
        "state": tool_request.state,
        "state_message": tool_request.state_message,
    }
    return ToolRequestModel.model_validate(as_dict)


def tool_request_detailed_to_model(tool_request: ToolRequest, security: IdEncodingHelper) -> ToolRequestDetailedModel:
    parsed = _parsed_tool_source_from_row(tool_request.tool_execution_state.tool_source)
    encoded_request = _encode_request_payload(_tool_request_payload_or_empty(tool_request), parsed, security)
    jobs = [{"src": "job", "id": job.id} for job in tool_request.jobs]
    tes = tool_request.tool_execution_state
    associations = tes.implicit_collection_associations if tes is not None else []
    implicit_collections = [
        {"src": "hdca", "id": assoc.dataset_collection_id, "output_name": assoc.output_name} for assoc in associations
    ]
    as_dict = {
        "id": tool_request.id,
        "request": encoded_request,
        "state": tool_request.state,
        "state_message": tool_request.state_message,
        "jobs": jobs,
        "implicit_collections": implicit_collections,
    }
    model = ToolRequestDetailedModel.model_validate(as_dict)
    return model


def tool_execution_to_model(
    tes: ToolExecutionState,
    security: IdEncodingHelper,
) -> ToolExecutionModel:
    """Serialize a ``ToolExecutionState`` for the read-only
    ``/api/tool_executions/{id}`` surface. Source-neutral: encodes the
    captured payload regardless of whether the row was minted by the
    async tool-request API or by workflow tool-step capture."""
    if tes.request:
        parsed = _parsed_tool_source_from_row(tes.tool_source)
        encoded_request = _encode_request_payload(tes.request, parsed, security)
    else:
        encoded_request = None
    jobs = [{"src": "job", "id": tes.job.id}] if tes.job is not None else []
    as_dict = {
        "id": security.encode_id(tes.id, kind=TOOL_EXECUTION_STATE_ENCODE_KIND),
        "create_time": tes.create_time,
        "update_time": tes.update_time,
        "request": encoded_request,
        "state": tes.state,
        "jobs": jobs,
    }
    return ToolExecutionModel.model_validate(as_dict)
