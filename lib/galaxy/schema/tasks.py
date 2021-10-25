from pydantic import BaseModel

from ..schema import PdfDocumentType


class PrepareDatasetCollectionDownload(BaseModel):
    short_term_storage_request_id: str
    history_dataset_collection_association_id: int


class GeneratePdfDownload(BaseModel):
    short_term_storage_request_id: str
    # basic markdown - Galaxy directives need to be processed before handing off to this task
    basic_markdown: str
    document_type: PdfDocumentType
