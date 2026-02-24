from collections.abc import Iterable
from typing import (
    TYPE_CHECKING,
)

from galaxy.exceptions import RequestParameterMissingException
from galaxy.model import (
    DatasetCollection,
    DatasetCollectionElement,
    HistoryDatasetAssociation,
)
from ..types import BaseDatasetCollectionType

if TYPE_CHECKING:
    from . import DatasetInstanceMapping


class RecordDatasetCollectionType(BaseDatasetCollectionType):
    """Arbitrary CWL-style record type."""

    collection_type = "record"

    def generate_elements(
        self, dataset_instances: "DatasetInstanceMapping", **kwds
    ) -> Iterable[DatasetCollectionElement]:
        fields = kwds.get("fields", None)
        if fields is None:
            raise RequestParameterMissingException("Missing or null parameter 'fields' required for record types.")
        if len(dataset_instances) != len(fields):
            self._validation_failed("Supplied element do not match fields.")
        index = 0
        for identifier, element in dataset_instances.items():
            field = fields[index]
            if field["name"] != identifier:
                self._validation_failed("Supplied element do not match fields.")

            # TODO: validate type and such.
            association = DatasetCollectionElement(
                element=element,
                element_identifier=identifier,
            )
            yield association
            index += 1

    def prototype_elements(self, fields=None, **kwds):
        if fields is None:
            raise RequestParameterMissingException("Missing or null parameter 'fields' required for record types.")
        for field in fields:
            name = field.get("name", None)
            assert name
            field_type = field.get("type", "File")
            if isinstance(field_type, dict) and field_type.get("type") == "array":
                sub_collection = DatasetCollection(collection_type="list")
                field_element = DatasetCollectionElement(
                    element=sub_collection,
                    element_identifier=name,
                )
            else:
                field_element = DatasetCollectionElement(
                    element=HistoryDatasetAssociation(),
                    element_identifier=name,
                )
            yield field_element
