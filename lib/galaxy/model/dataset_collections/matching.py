from collections.abc import (
    ItemsView,
    Iterator,
)
from dataclasses import dataclass
from typing import TYPE_CHECKING

from galaxy import exceptions
from .structure import (
    get_collection,
    get_structure,
    Leaf,
    leaf,
)

if TYPE_CHECKING:
    from galaxy.model import (
        DatasetCollection,
        DatasetCollectionElement,
    )
    from .structure import (
        BaseTree,
        CollectionLike,
        Structure,
        WhenValues,
    )
    from .type_description import (
        CollectionTypeDescription,
        CollectionTypeDescriptionFactory,
    )

CANNOT_MATCH_ERROR_MESSAGE = "Cannot match collection types."


@dataclass
class CollectionToMatch:
    """One input's collection and how it participates in matching."""

    hdca: "CollectionLike"
    # Declared as a string by tool inputs and as a description object by
    # workflow map-over planning; both are accepted throughout.
    subcollection_type: "str | CollectionTypeDescription | None" = None
    linked: bool = True


class CollectionsToMatch:
    """Structure representing a set of collections that need to be matched up
    when running tools and workflow steps.
    """

    def __init__(self) -> None:
        self.collections: dict[str, CollectionToMatch] = {}

    def add(
        self,
        input_name: str,
        hdca: "CollectionLike",
        subcollection_type: "str | CollectionTypeDescription | None" = None,
        linked: bool = True,
    ) -> None:
        self.collections[input_name] = CollectionToMatch(
            hdca=hdca,
            subcollection_type=subcollection_type,
            linked=linked,
        )

    def has_collections(self) -> bool:
        return len(self.collections) > 0

    def items(self) -> ItemsView[str, CollectionToMatch]:
        return self.collections.items()


class MatchingCollections:
    """Structure holding the result of matching a list of collections
    together. This class being different than the class above and being
    created in the DatasetCollectionManager layer may seem like
    overkill but I suspect in the future plugins will be subtypable for
    instance so matching collections will need to make heavy use of the
    dataset collection type registry managed by the dataset collections
    service - hence the complexity now.
    """

    def __init__(self) -> None:
        self.linked_structure: BaseTree | None = None
        self.unlinked_structures: list[BaseTree] = []
        self.collections: dict[str, CollectionLike] = {}
        self.subcollection_types: dict[str, str | CollectionTypeDescription | None] = {}
        self.action_tuples: dict[str, list[tuple[str, int]]] = {}
        self.when_values: WhenValues | None = None

    def __attempt_add_to_linked_match(
        self,
        input_name: str,
        hdca: "CollectionLike",
        child_collection: "DatasetCollection",
        collection_type_description: "CollectionTypeDescription",
        subcollection_type: "str | CollectionTypeDescription | None",
    ) -> None:
        structure = get_structure(
            child_collection, collection_type_description, leaf_subcollection_type=subcollection_type
        )
        if not self.linked_structure:
            self.linked_structure = structure
            self.collections[input_name] = hdca
            self.subcollection_types[input_name] = subcollection_type
        else:
            if not self.linked_structure.compatible_shape(structure):
                raise exceptions.MessageException(CANNOT_MATCH_ERROR_MESSAGE)
            self.collections[input_name] = hdca
            self.subcollection_types[input_name] = subcollection_type

    def slice_collections(self) -> Iterator[tuple[dict[str, "DatasetCollectionElement"], bool | None]]:
        """Yield the elements of each linked collection for every mapped execution."""
        linked_structure = self.linked_structure
        assert linked_structure is not None
        linked_structure.when_values = self.when_values
        return linked_structure.walk_collections({k: get_collection(v) for k, v in self.collections.items()})

    def subcollection_mapping_type(self, input_name: str) -> "str | CollectionTypeDescription | None":
        return self.subcollection_types[input_name]

    @property
    def structure(self) -> "BaseTree | None":
        """Cross product of all unlinked collection structures with the linked collection structure.

        ``None`` when nothing is mapped over.
        """
        effective_structure: Structure = leaf
        for unlinked_structure in self.unlinked_structures:
            effective_structure = effective_structure.multiply(unlinked_structure)
        effective_structure = effective_structure.multiply(self.linked_structure or leaf)
        if isinstance(effective_structure, Leaf):
            return None
        effective_structure.when_values = self.when_values
        return effective_structure

    def map_over_action_tuples(self, input_name: str) -> list[tuple[str, int]]:
        if input_name not in self.action_tuples:
            collection_instance = self.collections[input_name]
            self.action_tuples[input_name] = get_collection(collection_instance).dataset_action_tuples
        return self.action_tuples[input_name]

    def is_mapped_over(self, input_name: str) -> bool:
        return input_name in self.collections

    @staticmethod
    def for_collections(
        collections_to_match: CollectionsToMatch,
        collection_type_descriptions: "CollectionTypeDescriptionFactory",
    ) -> "MatchingCollections | None":
        if not collections_to_match.has_collections():
            return None

        matching_collections = MatchingCollections()
        for input_key, to_match in sorted(collections_to_match.items()):
            hdca = to_match.hdca
            # Resolve the contained collection: for an HDCA this is
            # hdca.collection; for a DCE it is dce.child_collection
            # (not dce.collection which is the *parent*).
            # Both collection_type_description and get_structure must
            # use the same collection so the type and elements agree.
            child_collection = get_collection(hdca)
            collection_type_description: CollectionTypeDescription = collection_type_descriptions.for_collection_type(
                child_collection.collection_type
            )
            subcollection_type = to_match.subcollection_type

            if to_match.linked:
                matching_collections.__attempt_add_to_linked_match(
                    input_key, hdca, child_collection, collection_type_description, subcollection_type
                )
            else:
                structure = get_structure(
                    child_collection,
                    collection_type_description,
                    leaf_subcollection_type=subcollection_type,
                )
                matching_collections.unlinked_structures.append(structure)

        return matching_collections
