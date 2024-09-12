import json
from uuid import uuid4

from pydantic import UUID4

from galaxy.schema.schema import (
    ClaimLandingPayload,
    CreateToolLandingRequestPayload,
    CreateWorkflowLandingRequestPayload,
    ToolLandingRequest,
    WorkflowLandingRequest,
)
from galaxy.structured_app import StructuredApp
from .context import ProvidesUserContext


class LandingRequestManager:

    def __init__(self, app: StructuredApp):
        self.app = app

    def create_tool_landing_request(self, payload: CreateToolLandingRequestPayload) -> ToolLandingRequest:
        response_model = ToolLandingRequest(
            tool_id=payload.tool_id,
            tool_version=payload.tool_version,
            request_state=payload.request_state,
            uuid=uuid4(),
            state="unclaimed",
        )

        with open("request.json", "w") as f:
            f.write(json.dumps(response_model.model_dump(mode="json")))
        return response_model

    def create_workflow_landing_request(self, payload: CreateWorkflowLandingRequestPayload) -> WorkflowLandingRequest:
        response_model = WorkflowLandingRequest(
            workflow_id=payload.workflow_id,
            workflow_target_type=payload.workflow_target_type,
            request_state=payload.request_state,
            uuid=uuid4(),
            state="unclaimed",
        )

        with open("request.json", "w") as f:
            f.write(json.dumps(response_model.model_dump(mode="json")))
        return response_model

    def claim_tool_landing_request(
        self, trans: ProvidesUserContext, uuid: UUID4, claim: ClaimLandingPayload
    ) -> ToolLandingRequest:
        with open("request.json", "r") as f_in:
            request = ToolLandingRequest.model_validate(json.load(f_in))
        request.state = "claimed"

        with open("request.json", "w") as f_out:
            f_out.write(json.dumps(request.model_dump(mode="json")))
        return request

    def claim_workflow_landing_request(
        self, trans: ProvidesUserContext, uuid: UUID4, claim: ClaimLandingPayload
    ) -> WorkflowLandingRequest:
        with open("request.json", "r") as f_in:
            request = WorkflowLandingRequest.model_validate(json.load(f_in))
        request.state = "claimed"

        with open("request.json", "w") as f_out:
            f_out.write(json.dumps(request.model_dump(mode="json")))
        return request

    def get_tool_landing_request(self, trans: ProvidesUserContext, uuid: UUID4) -> ToolLandingRequest:
        with open("request.json", "r") as f_in:
            request = ToolLandingRequest.model_validate(json.load(f_in))
        return request

    def get_workflow_landing_request(self, trans: ProvidesUserContext, uuid: UUID4) -> WorkflowLandingRequest:
        with open("request.json", "r") as f_in:
            request = WorkflowLandingRequest.model_validate(json.load(f_in))
        return request
