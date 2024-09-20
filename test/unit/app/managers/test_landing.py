from typing import (
    cast,
    List,
)
from uuid import uuid4

from galaxy.exceptions import (
    InsufficientPermissionsException,
    ItemAlreadyClaimedException,
    ObjectNotFound,
)
from galaxy.managers.landing import LandingRequestManager
from galaxy.model import (
    StoredWorkflow,
    Workflow,
)
from galaxy.model.base import transaction
from galaxy.schema.schema import (
    ClaimLandingPayload,
    CreateToolLandingRequestPayload,
    CreateWorkflowLandingRequestPayload,
    LandingRequestState,
    ToolLandingRequest,
    WorkflowLandingRequest,
)
from galaxy.structured_app import MinimalManagerApp
from galaxy.tool_util.parameters import (
    DataParameterModel,
    ToolParameterT,
)
from .base import BaseTestCase

TEST_TOOL_ID = "cat1"
TEST_TOOL_VERSION = "1.0.0"
TEST_STATE = {
    "input1": {
        "src": "url",
        "url": "https://raw.githubusercontent.com/galaxyproject/planemo/7be1bf5b3971a43eaa73f483125bfb8cabf1c440/tests/data/hello.txt",
        "ext": "txt",
    },
}
CLIENT_SECRET = "mycoolsecret"


class MockApp:

    @property
    def toolbox(self):
        return MockToolbox()


class MockToolbox:

    def get_tool(self, tool_id, tool_uuid, tool_version):
        return MockTool()


class MockTool:

    @property
    def parameters(self) -> List[ToolParameterT]:
        return [DataParameterModel(name="input1")]


class TestLanding(BaseTestCase):

    def setUp(self):
        super().setUp()
        self.landing_manager = LandingRequestManager(
            self.trans.sa_session,
            self.app.security,
            cast(MinimalManagerApp, MockApp()),
        )

    def test_tool_landing_requests_typical_flow(self):
        landing_request: ToolLandingRequest = self.landing_manager.create_tool_landing_request(self._tool_request)
        assert landing_request.state == LandingRequestState.UNCLAIMED
        assert landing_request.uuid is not None
        uuid = landing_request.uuid
        claim_payload = ClaimLandingPayload(client_secret=CLIENT_SECRET)
        landing_request = self.landing_manager.claim_tool_landing_request(self.trans, uuid, claim_payload)
        assert landing_request.state == LandingRequestState.CLAIMED
        assert landing_request.uuid == uuid
        landing_request = self.landing_manager.get_tool_landing_request(self.trans, uuid)
        assert landing_request.state == LandingRequestState.CLAIMED
        assert landing_request.uuid == uuid

    def test_tool_landing_requests_requires_matching_client_secret(self):
        landing_request: ToolLandingRequest = self.landing_manager.create_tool_landing_request(self._tool_request)
        uuid = landing_request.uuid
        claim_payload = ClaimLandingPayload(client_secret="wrongsecret")
        exception = None
        try:
            self.landing_manager.claim_tool_landing_request(self.trans, uuid, claim_payload)
        except InsufficientPermissionsException as e:
            exception = e
        assert exception is not None

    def test_tool_landing_requests_get_requires_claim(self):
        landing_request: ToolLandingRequest = self.landing_manager.create_tool_landing_request(self._tool_request)
        uuid = landing_request.uuid
        exception = None
        try:
            self.landing_manager.get_tool_landing_request(self.trans, uuid)
        except InsufficientPermissionsException as e:
            exception = e
        assert exception is not None

    def test_cannot_reclaim_tool_landing(self):
        landing_request: ToolLandingRequest = self.landing_manager.create_tool_landing_request(self._tool_request)
        assert landing_request.state == LandingRequestState.UNCLAIMED
        uuid = landing_request.uuid
        claim_payload = ClaimLandingPayload(client_secret=CLIENT_SECRET)
        landing_request = self.landing_manager.claim_tool_landing_request(self.trans, uuid, claim_payload)
        assert landing_request.state == LandingRequestState.CLAIMED
        exception = None
        try:
            self.landing_manager.claim_tool_landing_request(self.trans, uuid, claim_payload)
        except ItemAlreadyClaimedException as e:
            exception = e
        assert exception

    def test_get_tool_unknown_claim(self):
        exception = None
        try:
            self.landing_manager.get_tool_landing_request(self.trans, uuid4())
        except ObjectNotFound as e:
            exception = e
        assert exception

    def test_stored_workflow_landing_requests_typical_flow(self):
        landing_request: WorkflowLandingRequest = self.landing_manager.create_workflow_landing_request(
            self._stored_workflow_request
        )
        assert landing_request.state == LandingRequestState.UNCLAIMED
        assert landing_request.uuid is not None
        assert landing_request.workflow_target_type == "stored_workflow"
        uuid = landing_request.uuid
        claim_payload = ClaimLandingPayload(client_secret=CLIENT_SECRET)
        landing_request = self.landing_manager.claim_workflow_landing_request(self.trans, uuid, claim_payload)
        assert landing_request.state == LandingRequestState.CLAIMED
        assert landing_request.uuid == uuid
        assert landing_request.workflow_target_type == "stored_workflow"
        landing_request = self.landing_manager.get_workflow_landing_request(self.trans, uuid)
        assert landing_request.state == LandingRequestState.CLAIMED
        assert landing_request.uuid == uuid
        assert landing_request.workflow_target_type == "stored_workflow"

    def test_workflow_landing_requests_typical_flow(self):
        landing_request: WorkflowLandingRequest = self.landing_manager.create_workflow_landing_request(
            self._workflow_request
        )
        assert landing_request.state == LandingRequestState.UNCLAIMED
        assert landing_request.uuid is not None
        assert landing_request.workflow_target_type == "workflow"
        uuid = landing_request.uuid
        claim_payload = ClaimLandingPayload(client_secret=CLIENT_SECRET)
        landing_request = self.landing_manager.claim_workflow_landing_request(self.trans, uuid, claim_payload)
        assert landing_request.state == LandingRequestState.CLAIMED
        assert landing_request.uuid == uuid
        assert landing_request.workflow_target_type == "workflow"
        landing_request = self.landing_manager.get_workflow_landing_request(self.trans, uuid)
        assert landing_request.state == LandingRequestState.CLAIMED
        assert landing_request.uuid == uuid
        assert landing_request.workflow_target_type == "workflow"

    @property
    def _tool_request(self) -> CreateToolLandingRequestPayload:
        return CreateToolLandingRequestPayload(
            tool_id=TEST_TOOL_ID,
            tool_version=TEST_TOOL_VERSION,
            request_state=TEST_STATE.copy(),
            client_secret=CLIENT_SECRET,
        )

    @property
    def _stored_workflow_request(self) -> CreateWorkflowLandingRequestPayload:
        sa_session = self.app.model.context
        stored_workflow = StoredWorkflow()
        stored_workflow.user = self.trans.user
        sa_session.add(stored_workflow)
        with transaction(sa_session):
            sa_session.commit()

        return CreateWorkflowLandingRequestPayload(
            workflow_id=self.app.security.encode_id(stored_workflow.id),
            workflow_target_type="stored_workflow",
            request_state=TEST_STATE.copy(),
            client_secret=CLIENT_SECRET,
        )

    @property
    def _workflow_request(self) -> CreateWorkflowLandingRequestPayload:
        sa_session = self.app.model.context
        stored_workflow = StoredWorkflow()
        stored_workflow.user = self.trans.user
        workflow = Workflow()
        workflow.stored_workflow = stored_workflow
        sa_session.add(stored_workflow)
        sa_session.add(workflow)
        with transaction(sa_session):
            sa_session.commit()

        return CreateWorkflowLandingRequestPayload(
            workflow_id=self.app.security.encode_id(workflow.id),
            workflow_target_type="workflow",
            request_state=TEST_STATE.copy(),
            client_secret=CLIENT_SECRET,
        )
