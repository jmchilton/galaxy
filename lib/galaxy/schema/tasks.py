from enum import Enum

from pydantic import BaseModel, Field

from .schema import DatasetSourceType


class PdfDocumentType(str, Enum):
    invocation_report = "invocation_report"
    page = "page"


class PrepareDatasetCollectionDownload(BaseModel):
    short_term_storage_request_id: str
    history_dataset_collection_association_id: int


class GeneratePdfDownload(BaseModel):
    short_term_storage_request_id: str
    # basic markdown - Galaxy directives need to be processed before handing off to this task
    basic_markdown: str
    document_type: PdfDocumentType


# serialize user info for tasks
class RequestUser(BaseModel):
    user_id: int
    # TODO: allow make the above optional and allow a session_id for anonymous users...
    # session_id: Optional[str]


class MaterializeDatasetInstanceTaskRequest(BaseModel):
    history_id: int
    user: RequestUser
    source: DatasetSourceType = Field(
        None,
        title="Source",
        description="The source of the content. Can be other history element to be copied or library elements.",
    )
    content: int = Field(
        None,
        title="Content",
        description=(
            "Depending on the `source` it can be:\n"
            "- The unencoded id from the library dataset\n"
            "- The unencoded id from the HDA\n"
        ),
    )
