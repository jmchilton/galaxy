import logging

log = logging.getLogger(__name__)


class HistoryQuery:
    """An object for describing the collections to pull out of a history,
    used by DataCollectionToolParameter.
    """

    def __init__(self, **kwargs):
        self.collection_type_descriptions = kwargs.get("collection_type_descriptions", None)

    @staticmethod
    def from_collection_type(collection_type, collection_type_descriptions):
        kwargs = dict(collection_type_descriptions=[collection_type_descriptions.for_collection_type(collection_type)])
        return HistoryQuery(**kwargs)

    @staticmethod
    def from_collection_types(collection_types, collection_type_descriptions):
        if collection_types:
            sort = collection_type_descriptions.sort_by_specificity
            collection_type_descriptions = [
                collection_type_descriptions.for_collection_type(t) for t in collection_types
            ]
            # see comments on CollectionTypeDescriptionFactory.sort_by_specificity
            # for why this is sorted correctly for subcollection mapping logic.
            collection_type_descriptions = sort(collection_type_descriptions)
            log.info("HistoryQuery: sorted collection types: %s", collection_type_descriptions)
        else:
            collection_type_descriptions = None
        kwargs = dict(collection_type_descriptions=collection_type_descriptions)
        return HistoryQuery(**kwargs)

    @staticmethod
    def from_parameter(param, collection_type_descriptions):
        """Take in a tool parameter element."""
        collection_types = param.collection_types
        return HistoryQuery.from_collection_types(collection_types, collection_type_descriptions)

    def direct_match(self, hdca):
        collection_type_descriptions = self.collection_type_descriptions
        if collection_type_descriptions is not None:
            for collection_type_description in collection_type_descriptions:
                matches = collection_type_description.can_match_type(hdca.collection.collection_type)
                if matches:
                    return True
            return False

        return True

    def can_map_over(self, hdca):
        collection_type_descriptions = self.collection_type_descriptions
        if collection_type_descriptions is None:
            return False

        hdca_collection_type = hdca.collection.collection_type
        for collection_type_description in collection_type_descriptions:
            # See note about the way this is sorted above.
            if collection_type_description.is_subcollection_of_type(hdca_collection_type):
                return collection_type_description
        return False
