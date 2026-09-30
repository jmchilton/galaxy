"""
API operations on tool license agreements and users' acceptance of them.
"""

import logging
from typing import Annotated

from fastapi import (
    Path,
    Query,
    Response,
    status,
)

from galaxy.managers.context import ProvidesUserContext
from galaxy.schema.fields import DecodedDatabaseIdField
from galaxy.schema.license_agreements import (
    CreateLicenseAcceptancePayload,
    LicenseAcceptanceResponse,
    ToolLicenseAgreementsResponse,
    UserLicenseAcceptancesResponse,
    WorkflowLicenseAgreementsResponse,
)
from galaxy.schema.schema import FlexibleUserIdType
from galaxy.webapps.galaxy.api import (
    depends,
    DependsOnTrans,
    Router,
)
from galaxy.webapps.galaxy.api.common import (
    ToolIDPathParam,
    ToolVersionQueryParam,
)
from galaxy.webapps.galaxy.services.license_agreements import LicenseAgreementsService

log = logging.getLogger(__name__)

router = Router(tags=["license agreements"])

StoredWorkflowIdPathParam = Annotated[
    DecodedDatabaseIdField,
    Path(..., title="Stored Workflow ID", description="The encoded database identifier of the Stored Workflow."),
]

AgreementHashPathParam: str = Path(
    ...,
    title="Agreement hash",
    description="Content address of the accepted agreement.",
    pattern="^[0-9a-f]{64}$",
)


@router.cbv
class FastAPILicenseAgreements:
    service: LicenseAgreementsService = depends(LicenseAgreementsService)

    @router.get(
        "/api/tools/{tool_id:path}/license_agreements",
        summary="Return the license agreements a tool declares and whether the current user accepts them.",
    )
    def tool_license_agreements(
        self,
        tool_id: str = ToolIDPathParam,
        tool_version: str | None = ToolVersionQueryParam,
        trans: ProvidesUserContext = DependsOnTrans,
    ) -> ToolLicenseAgreementsResponse:
        return self.service.tool_license_agreements(trans, tool_id, tool_version)

    @router.get(
        "/api/workflows/{workflow_id}/license_agreements",
        summary="Return the license agreements a workflow's tools declare, including in subworkflows.",
    )
    def workflow_license_agreements(
        self,
        workflow_id: StoredWorkflowIdPathParam,
        version: int | None = Query(None, description="The workflow version; the latest when omitted."),
        trans: ProvidesUserContext = DependsOnTrans,
    ) -> WorkflowLicenseAgreementsResponse:
        return self.service.workflow_license_agreements(trans, workflow_id, version)

    @router.get(
        "/api/users/{user_id}/license_acceptances",
        summary="List the license agreements the user currently accepts.",
    )
    def list_license_acceptances(
        self,
        user_id: FlexibleUserIdType,
        trans: ProvidesUserContext = DependsOnTrans,
        include_history: bool = Query(
            False,
            description="Whether to include every acceptance and revocation, oldest first.",
        ),
    ) -> UserLicenseAcceptancesResponse:
        return self.service.list_acceptances(trans, user_id, include_history)

    @router.post(
        "/api/users/{user_id}/license_acceptances",
        summary="Persistently accept a license agreement declared by a tool.",
    )
    def accept_license_agreement(
        self,
        user_id: FlexibleUserIdType,
        payload: CreateLicenseAcceptancePayload,
        trans: ProvidesUserContext = DependsOnTrans,
    ) -> LicenseAcceptanceResponse:
        return self.service.accept(trans, user_id, payload)

    @router.delete(
        "/api/users/{user_id}/license_acceptances/{agreement_hash}",
        summary="Revoke the user's persistent acceptance of a license agreement.",
        status_code=status.HTTP_204_NO_CONTENT,
    )
    def revoke_license_acceptance(
        self,
        user_id: FlexibleUserIdType,
        agreement_hash: str = AgreementHashPathParam,
        trans: ProvidesUserContext = DependsOnTrans,
    ) -> Response:
        self.service.revoke(trans, user_id, agreement_hash)
        return Response(status_code=status.HTTP_204_NO_CONTENT)
