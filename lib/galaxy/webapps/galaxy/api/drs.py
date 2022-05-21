"""Implement a DRS server for Galaxy dataset objects (experimental)."""
import logging
from io import IOBase

from fastapi import (
    Path,
    Request,
)
from starlette.responses import (
    FileResponse,
    StreamingResponse,
)

from galaxy.exceptions import ObjectNotFound
from galaxy.managers.context import ProvidesHistoryContext
from galaxy.schema.drs import (
    DrsObject,
    Service,
    ServiceOrganization,
    ServiceType,
)
from galaxy.schema.fields import EncodedDatabaseIdField
from galaxy.structured_app import StructuredApp
from galaxy.util.zipstream import ZipstreamWrapper
from galaxy.version import VERSION
from galaxy.webapps.galaxy.services.datasets import DatasetsService
from . import (
    depends,
    DependsOnTrans,
    Router,
)

log = logging.getLogger(__name__)
router = Router(tags=["drs"])
ObjectIDParam: EncodedDatabaseIdField = Path(..., title="Object ID", description="The ID of the group")
AccessIDParam: str = Path(
    ..., title="Access ID", description="The access ID of the access method for objects, unused in Galaxy."
)

DRS_SERVICE_NAME = "Galaxy DRS API"
DRS_SERVICE_DESCRIPTION = "Serves Galaxy datasets according to the GA4GH DRS specification"


@router.cbv
class DrsApi:
    service: DatasetsService = depends(DatasetsService)
    app: StructuredApp = depends(StructuredApp)

    @router.get("/ga4gh/drs/v1/service-info")
    def service_info(self, request: Request) -> Service:
        components = request.url.components
        hostname = components.hostname
        assert hostname
        default_organization_id = ".".join(reversed(hostname.split(".")))
        config = self.app.config
        organization_id = config.ga4gh_service_id or default_organization_id
        organization_name = config.ga4gh_service_organization_name or organization_id
        organization_url = config.ga4gh_service_organization_url or f"{components.scheme}://{components.netloc}"

        organization = ServiceOrganization(
            url=organization_url,
            name=organization_name,
        )
        service_type = ServiceType(
            group="org.ga4gh",
            artifact="drs",
            version="1.2.0",
        )
        return Service(
            id=organization_id + ".drs",
            name=DRS_SERVICE_NAME,
            description=DRS_SERVICE_DESCRIPTION,
            organization=organization,
            type=service_type,
            version=VERSION,
        )

    @router.get("/ga4gh/drs/v1/objects/{object_id}")
    @router.post("/ga4gh/drs/v1/objects/{object_id}")  # spec specifies both get and post should work.
    def get_object(
        self,
        request: Request,
        trans: ProvidesHistoryContext = DependsOnTrans,
        object_id: EncodedDatabaseIdField = ObjectIDParam,
    ) -> DrsObject:
        return self.service.get_drs_object(trans, object_id, request_url=request.url)

    @router.get("/ga4gh/drs/v1/objects/{object_id}/access/{access_id}")
    @router.post("/ga4gh/drs/v1/objects/{object_id}/access/{access_id}")
    def get_access_url(
        self,
        request: Request,
        trans: ProvidesHistoryContext = DependsOnTrans,
        object_id: EncodedDatabaseIdField = ObjectIDParam,
        access_id: str = AccessIDParam,
    ):
        raise ObjectNotFound("Access IDs are not implemented for this DRS server")

    @router.get(
        "/api/drs_download/{object_id}",
        response_class=StreamingResponse,
    )
    def download(
        self, trans: ProvidesHistoryContext = DependsOnTrans, object_id: EncodedDatabaseIdField = ObjectIDParam
    ):
        display_data, headers = self.service.display(trans, object_id, False, None, None, True)
        if isinstance(display_data, IOBase):
            file_name = getattr(display_data, "name", None)
            if file_name:
                return FileResponse(file_name, headers=headers)
        elif isinstance(display_data, ZipstreamWrapper):
            return StreamingResponse(display_data.response(), headers=headers)
        return StreamingResponse(display_data, headers=headers)
