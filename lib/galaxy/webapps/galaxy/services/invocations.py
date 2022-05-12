from enum import Enum
from typing import (
    Any,
    Dict,
    List,
    Optional,
    Tuple,
)

from pydantic import (
    BaseModel,
    Field,
)

from galaxy.celery.tasks import prepare_invocation_download
from galaxy.exceptions import (
    AdminRequiredException,
    ObjectNotFound,
)
from galaxy.managers.histories import HistoryManager
from galaxy.managers.workflows import WorkflowsManager
from galaxy.schema.fields import EncodedDatabaseIdField
from galaxy.schema.schema import (
    AsyncFile,
    InvocationIndexQueryPayload,
    Model,
)
from galaxy.schema.tasks import GenerateInvocationDownload
from galaxy.security.idencoding import IdEncodingHelper
from galaxy.web.short_term_storage import ShortTermStorageAllocator
from galaxy.webapps.galaxy.services.base import (
    async_task_summary,
    ensure_celery_tasks_enabled,
    model_store_storage_target,
    ServiceBase,
)


class InvocationSerializationView(str, Enum):
    element = "element"
    collection = "collection"


class InvocationSerializationParams(BaseModel):
    """Contains common parameters for customizing model serialization."""

    view: Optional[InvocationSerializationView] = Field(
        default=None,
        title="View",
        description=(
            "The name of the view used to serialize this item. "
            "This will return a predefined set of attributes of the item."
        ),
        example="element",
    )
    step_details: bool = Field(
        default=False, title="Include step details", description="Include details for individual invocation steps."
    )
    legacy_job_state: bool = Field(
        default=False,
        deprecated=True,
    )


class InvocationIndexPayload(InvocationIndexQueryPayload):
    instance: bool = Field(default=False, description="Is provided workflow id for Workflow instead of StoredWorkflow?")


class PrepareStoreDownloadPayload(Model):
    model_store_format: str = Field(default="tar.gz")
    include_files: bool = Field(default=False)


class InvocationsService(ServiceBase):
    def __init__(
        self,
        security: IdEncodingHelper,
        histories_manager: HistoryManager,
        workflows_manager: WorkflowsManager,
        short_term_storage_allocator: ShortTermStorageAllocator,
    ):
        super().__init__(security=security)
        self._histories_manager = histories_manager
        self._workflows_manager = workflows_manager
        self.short_term_storage_allocator = short_term_storage_allocator

    def index(
        self, trans, invocation_payload: InvocationIndexPayload, serialization_params: InvocationSerializationParams
    ) -> Tuple[List[Dict[str, Any]], int]:
        workflow_id = invocation_payload.workflow_id
        if invocation_payload.instance:
            instance = invocation_payload.instance
            invocation_payload.workflow_id = self._workflows_manager.get_stored_workflow(
                trans, workflow_id, by_stored_id=not instance
            ).id
        if invocation_payload.history_id:
            # access check
            self._histories_manager.get_accessible(
                invocation_payload.history_id, trans.user, current_history=trans.history
            )
        if not trans.user_is_admin:
            # We restrict the query to the current users' invocations
            # Endpoint requires user login, so trans.user.id is never None
            # TODO: user_id should be optional!
            user_id = trans.user.id
            if invocation_payload.user_id and invocation_payload.user_id != user_id:
                raise AdminRequiredException("Only admins can index the invocations of others")
        else:
            # Get all invocations if user is admin (and user_id is None).
            # xref https://github.com/galaxyproject/galaxy/pull/13862#discussion_r865732297
            user_id = invocation_payload.user_id
        invocations, total_matches = self._workflows_manager.build_invocations_query(
            trans,
            stored_workflow_id=invocation_payload.workflow_id,
            history_id=invocation_payload.history_id,
            job_id=invocation_payload.job_id,
            user_id=user_id,
            include_terminal=invocation_payload.include_terminal,
            limit=invocation_payload.limit,
            offset=invocation_payload.offset,
            sort_by=invocation_payload.sort_by,
            sort_desc=invocation_payload.sort_desc,
        )
        invocation_dict = self.serialize_workflow_invocations(invocations, serialization_params)
        return invocation_dict, total_matches

    def prepare_store_download(
        self, trans, invocation_id: EncodedDatabaseIdField, payload: PrepareStoreDownloadPayload
    ):
        ensure_celery_tasks_enabled(trans.app.config)
        model_store_format = payload.model_store_format
        include_files = payload.include_files
        decoded_workflow_invocation_id = self.decode_id(invocation_id)
        workflow_invocation = self._workflows_manager.get_invocation(trans, decoded_workflow_invocation_id, eager=True)
        if not workflow_invocation:
            raise ObjectNotFound()
        try:
            invocation_name = f"Invocation of {workflow_invocation.workflow.stored_workflow.name} at {workflow_invocation.create_time.isoformat()}"
        except AttributeError:
            invocation_name = f"Invocation of workflow at {workflow_invocation.create_time.isoformat()}"
        short_term_storage_target = model_store_storage_target(
            self.short_term_storage_allocator,
            invocation_name,
            model_store_format,
        )
        request = GenerateInvocationDownload(
            model_store_format=model_store_format,
            short_term_storage_request_id=short_term_storage_target.request_id,
            include_files=include_files,
            user=trans.async_request_user,
            invocation_id=workflow_invocation.id,
        )
        result = prepare_invocation_download.delay(request=request)
        return AsyncFile(storage_request_id=short_term_storage_target.request_id, task=async_task_summary(result))

    def serialize_workflow_invocation(
        self,
        invocation,
        params: InvocationSerializationParams,
        default_view: InvocationSerializationView = InvocationSerializationView.element,
    ):
        view = params.view or default_view
        step_details = params.step_details
        legacy_job_state = params.legacy_job_state
        as_dict = invocation.to_dict(view, step_details=step_details, legacy_job_state=legacy_job_state)
        return self.security.encode_all_ids(as_dict, recursive=True)

    def serialize_workflow_invocations(
        self,
        invocations,
        params: InvocationSerializationParams,
        default_view: InvocationSerializationView = InvocationSerializationView.collection,
    ):
        return list(
            map(lambda i: self.serialize_workflow_invocation(i, params, default_view=default_view), invocations)
        )
