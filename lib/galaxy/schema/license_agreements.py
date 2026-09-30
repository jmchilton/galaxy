from datetime import datetime
from typing import (
    Annotated,
    Literal,
)

from pydantic import (
    Field,
    RootModel,
)

from galaxy.schema.fields import EncodedDatabaseIdField
from galaxy.schema.schema import Model
from galaxy.tool_util_models.tool_source import LicenseAgreementBinds

AgreementHashField = Annotated[
    str,
    Field(
        description="Content address of the displayed affirmation and terms; identifies the agreement being accepted.",
        pattern="^[0-9a-f]{64}$",
    ),
]


class LicenseAgreementTermsResponse(Model):
    agreement_hash: AgreementHashField
    affirmation: Annotated[str, Field(description="The statement the user affirms.")]
    terms: Annotated[str, Field(description="The license terms exactly as displayed to the user.")]


class ToolLicenseAgreementResponse(LicenseAgreementTermsResponse):
    id: Annotated[str, Field(description="The agreement id declared by the tool.")]
    version: Annotated[str, Field(description="The agreement version declared by the tool.")]
    label: Annotated[str, Field(description="Short human-readable name of the agreement.")]
    url: Annotated[str | None, Field(description="Link to the license for reference; never fetched by Galaxy.")] = None
    binds: Annotated[
        LicenseAgreementBinds,
        Field(
            description="Whether the affirmation is about each submission ('submission') or about the user ('user'). "
            "Only 'user' agreements can be accepted persistently.",
        ),
    ]
    accepted: Annotated[
        bool,
        Field(description="Whether the current user's persistent acceptance satisfies this agreement."),
    ]


class ToolLicenseAgreementsResponse(RootModel[list[ToolLicenseAgreementResponse]]):
    root: list[ToolLicenseAgreementResponse]


class LicenseAgreementDeclaringStep(Model):
    path: Annotated[
        list[int],
        Field(description="Step order indices from the outermost workflow down to the step, through subworkflows."),
    ]
    tool_id: Annotated[str, Field(description="The step's tool.")]
    tool_version: Annotated[str, Field(description="The step's tool version.")]


class WorkflowLicenseAgreementResponse(ToolLicenseAgreementResponse):
    steps: Annotated[
        list[LicenseAgreementDeclaringStep], Field(description="The workflow steps whose tools declare the agreement.")
    ]


class WorkflowLicenseAgreementsResponse(RootModel[list[WorkflowLicenseAgreementResponse]]):
    root: list[WorkflowLicenseAgreementResponse]


class LicenseAcceptanceEventResponse(Model):
    id: EncodedDatabaseIdField
    agreement_hash: AgreementHashField
    action: Annotated[Literal["accept", "revoke"], Field(description="Whether the agreement was accepted or revoked.")]
    license_id: Annotated[str | None, Field(description="The agreement id displayed when the event was recorded.")]
    license_version: Annotated[str | None, Field(description="The agreement version displayed.")]
    license_label: Annotated[str | None, Field(description="The agreement label displayed.")]
    license_url: Annotated[str | None, Field(description="The agreement URL displayed.")]
    granted_by: Annotated[
        Literal["user", "admin"], Field(description="Whether the user or an administrator recorded the event.")
    ]
    prompting_tool_id: Annotated[str | None, Field(description="The tool the agreement was accepted from.")]
    prompting_tool_version: Annotated[str | None, Field(description="The version of the prompting tool.")]
    create_time: datetime


class LicenseAcceptanceResponse(Model):
    agreement: LicenseAgreementTermsResponse
    event: Annotated[LicenseAcceptanceEventResponse, Field(description="The event that accepted the agreement.")]


class UserLicenseAcceptancesResponse(Model):
    accepted: Annotated[list[LicenseAcceptanceResponse], Field(description="Agreements the user currently accepts.")]
    history: Annotated[
        list[LicenseAcceptanceEventResponse] | None,
        Field(description="Every acceptance and revocation by the user, oldest first, when requested."),
    ] = None


class CreateLicenseAcceptancePayload(Model):
    tool_id: Annotated[str, Field(description="The tool declaring the agreement.")]
    tool_version: Annotated[str | None, Field(description="The tool version; the default version when omitted.")] = None
    license_id: Annotated[str, Field(description="The agreement id declared by the tool.")]
    agreement_hash: Annotated[
        AgreementHashField,
        Field(description="The agreement hash shown to the user, confirming which terms they accepted."),
    ]
