"""Module for reasoning about structure of and matching hierarchical collections of data."""

from abc import (
    ABC,
    abstractmethod,
)
from collections.abc import (
    Callable,
    Iterator,
)
from typing import (
    Any,
    TYPE_CHECKING,
    TypeAlias,
)

from galaxy.model import DatasetCollectionElement

if TYPE_CHECKING:
    from galaxy.managers.collections import DatasetCollectionManager
    from galaxy.model import (
        DatasetCollection,
        HistoryDatasetCollectionAssociation,
    )
    from galaxy.tool_util.parser.output_objects import ToolOutputCollection
    from galaxy.tool_util_models.sample_sheet import SampleSheetColumnDefinitions
    from .type_description import (
        CollectionTypeDescription,
        CollectionTypeLike,
    )

    CollectionLike: TypeAlias = DatasetCollectionElement | HistoryDatasetCollectionAssociation

# Per-element ``when`` values of a conditional step; a single entry applies to every element.
WhenValues: TypeAlias = list[bool | None]
# One mapped execution: the element sliced from each input, and its ``when`` value.
CollectionSlice: TypeAlias = tuple[dict[str, DatasetCollectionElement], bool | None]


class Leaf:
    children_known = True

    def __len__(self) -> int:
        return 1

    @property
    def is_leaf(self) -> bool:
        return True

    def clone(self) -> "Leaf":
        return self

    def multiply(self, other_structure: "Structure") -> "Structure":
        return other_structure.clone()

    def __str__(self) -> str:
        return "Leaf[]"


leaf = Leaf()


class BaseTree(ABC):
    """Structure of a collection: enumerated (``Tree``) or known only by type (``UninitializedTree``)."""

    children_known: bool
    when_values: WhenValues | None = None

    def __init__(self, collection_type_description: "CollectionTypeDescription") -> None:
        self.collection_type_description = collection_type_description

    @property
    def is_leaf(self) -> bool:
        return False

    @abstractmethod
    def __len__(self) -> int: ...

    @abstractmethod
    def walk_collections(self, collection_dict: dict[str, "DatasetCollection"]) -> Iterator[CollectionSlice]: ...

    @abstractmethod
    def compatible_shape(self, other_structure: "BaseTree") -> bool: ...

    @abstractmethod
    def clone(self) -> "BaseTree": ...

    @abstractmethod
    def multiply(self, other_structure: "Structure") -> "BaseTree": ...


# Any collection structure: a single dataset or a (possibly unenumerated) tree.
Structure: TypeAlias = Leaf | BaseTree


class UninitializedTree(BaseTree):
    children_known = False

    def __len__(self) -> int:
        raise _unknown_children("compute the cardinality")

    def walk_collections(self, collection_dict: dict[str, "DatasetCollection"]) -> Iterator[CollectionSlice]:
        raise _unknown_children("walk the elements")

    def compatible_shape(self, other_structure: BaseTree) -> bool:
        raise _unknown_children("compare the shape")

    def clone(self) -> "UninitializedTree":
        return self

    def multiply(self, other_structure: Structure) -> "UninitializedTree":
        if isinstance(other_structure, Leaf):
            return self.clone()

        new_collection_type = self.collection_type_description.multiply(other_structure.collection_type_description)
        return UninitializedTree(new_collection_type)

    def __str__(self) -> str:
        return f"UninitializedTree[collection_type={self.collection_type_description}]"


class Tree(BaseTree):
    children_known = True

    def __init__(
        self,
        children: list[tuple[str | None, Structure]],
        collection_type_description: "CollectionTypeDescription",
        when_values: WhenValues | None = None,
        columns_metadata: dict[str | None, Any] | None = None,
        column_definitions: "SampleSheetColumnDefinitions | None" = None,
    ) -> None:
        super().__init__(collection_type_description)
        self.children = children
        self.when_values = when_values
        # columns_metadata maps element_identifier (nullable in the model) to columns data
        self.columns_metadata = columns_metadata or {}
        self.column_definitions = column_definitions

    @staticmethod
    def for_dataset_collection(
        dataset_collection: "DatasetCollection", collection_type_description: "CollectionTypeDescription"
    ) -> "Tree":
        children: list[tuple[str | None, Structure]] = []
        columns_metadata: dict[str | None, Any] = {}
        for element in dataset_collection.elements:
            if collection_type_description.has_subcollections():
                subcollection_type_description = (
                    collection_type_description.subcollection_type_description()
                )  # Type description of children
                tree = Tree.for_dataset_collection(
                    _child_collection(element), collection_type_description=subcollection_type_description
                )
                children.append((element.element_identifier, tree))
            else:
                children.append((element.element_identifier, leaf))
            # Capture columns metadata from sample sheet collections
            if element.columns is not None:
                columns_metadata[element.element_identifier] = element.columns
        return Tree(
            children,
            collection_type_description,
            columns_metadata=columns_metadata,
            column_definitions=dataset_collection.column_definitions,
        )

    def walk_collections(self, collection_dict: dict[str, "DatasetCollection"]) -> Iterator[CollectionSlice]:
        for index, (_identifier, substructure) in enumerate(self.children):
            elements: dict[str, DatasetCollectionElement] = {
                name: collection[index] for name, collection in collection_dict.items()
            }
            when_value = None
            if self.when_values:
                if len(self.when_values) == 1:
                    when_value = self.when_values[0]
                else:
                    when_value = self.when_values[index]

            if isinstance(substructure, Leaf):
                yield elements, when_value
            else:
                sub_collections = {name: _child_collection(element) for name, element in elements.items()}
                for sub_elements, _when_value in substructure.walk_collections(sub_collections):
                    yield sub_elements, when_value

    def compatible_shape(self, other_structure: BaseTree) -> bool:
        """Symmetric sibling-matching check.

        Both sides have already passed connection-time edge validation;
        here we only compare shape. Uses ``compatible`` (not ``accepts``)
        so order of arrival does not change the answer.
        """
        if not isinstance(other_structure, Tree):
            raise _unknown_children("compare the shape")

        if not self.collection_type_description.compatible(other_structure.collection_type_description):
            return False

        if len(self.children) != len(other_structure.children):
            return False

        for (_, my_child), (_, other_child) in zip(self.children, other_structure.children):
            if isinstance(my_child, Leaf) and isinstance(other_child, Leaf):
                continue
            # A dataset never matches a nested collection.
            if isinstance(my_child, Leaf) or isinstance(other_child, Leaf):
                return False
            if not my_child.compatible_shape(other_child):
                return False

        return True

    def __len__(self) -> int:
        return sum(len(c[1]) for c in self.children)

    def multiply(self, other_structure: Structure) -> "Tree":
        if isinstance(other_structure, Leaf):
            return self.clone()

        new_collection_type = self.collection_type_description.multiply(other_structure.collection_type_description)
        new_children: list[tuple[str | None, Structure]] = []
        for identifier, structure in self.children:
            new_children.append((identifier, structure.multiply(other_structure)))

        # Preserve columns_metadata and column_definitions when multiplying
        return Tree(
            new_children,
            new_collection_type,
            columns_metadata=self.columns_metadata.copy(),
            column_definitions=self.column_definitions,
        )

    def clone(self) -> "Tree":
        cloned_children: list[tuple[str | None, Structure]] = [(_[0], _[1].clone()) for _ in self.children]
        return Tree(
            cloned_children,
            self.collection_type_description,
            columns_metadata=self.columns_metadata.copy(),
            column_definitions=self.column_definitions,
        )

    def __str__(self) -> str:
        return f"Tree[collection_type={self.collection_type_description},children=({','.join(f'{identifier_and_element[0]}={identifier_and_element[1]}' for identifier_and_element in self.children)})]"


def tool_output_to_structure(
    get_sliced_input_collection_structure: Callable[[str], BaseTree],
    tool_output: "ToolOutputCollection",
    collections_manager: "DatasetCollectionManager",
) -> Structure:
    tree: Structure
    if not tool_output.collection:
        tree = leaf
    else:
        collection_type_descriptions = collections_manager.collection_type_descriptions
        # Okay this is ToolCollectionOutputStructure not a Structure - different
        # concepts of structure.
        structured_like = tool_output.structure.structured_like
        collection_type = tool_output.structure.collection_type
        if structured_like:
            tree = get_sliced_input_collection_structure(structured_like)
            if collection_type and tree.collection_type_description.collection_type != collection_type:
                # See tool paired_collection_map_over_structured_like - type should
                # override structured_like if they disagree.
                tree = UninitializedTree(collection_type_descriptions.for_collection_type(collection_type))
        else:
            # Can't pre-compute the structure in this case, see if we can find a collection type.
            if collection_type is None and tool_output.structure.collection_type_source:
                collection_type = get_sliced_input_collection_structure(
                    tool_output.structure.collection_type_source
                ).collection_type_description.collection_type

            if not collection_type:
                raise Exception(f"Failed to determine collection type for mapping over output {tool_output.name}")

            tree = UninitializedTree(collection_type_descriptions.for_collection_type(collection_type))

    # TODO: We don't need to return UninitializedTree for pairs I think, we should build
    # a paired tree for the known structure here.
    return tree


def _child_collection(element: DatasetCollectionElement) -> "DatasetCollection":
    child_collection = element.child_collection
    assert child_collection is not None
    return child_collection


def _unknown_children(operation: str) -> NotImplementedError:
    return NotImplementedError(f"Cannot {operation} of a collection whose children are not known")


def get_collection(
    dataset_collection_instance: "CollectionLike",
) -> "DatasetCollection":
    """Return the DatasetCollection contained by a collection instance.

    A DatasetCollectionElement has two collection references:
      - ``collection``: the **parent** collection this element belongs to
      - ``child_collection``: the nested collection this element *contains*

    An HDCA has one:
      - ``collection``: the collection it wraps

    This helper returns the *contained* collection in both cases
    (child_collection for DCE, collection for HDCA/adapters) and is
    intended for callers that still hold a wrapper object and need a
    DatasetCollection to pass to ``get_structure`` or ``walk_collections``.
    """
    if (
        isinstance(dataset_collection_instance, DatasetCollectionElement)
        and dataset_collection_instance.child_collection
    ):
        return dataset_collection_instance.child_collection
    return dataset_collection_instance.collection


def get_structure(
    collection: "DatasetCollection",
    collection_type_description: "CollectionTypeDescription",
    leaf_subcollection_type: "CollectionTypeLike | None" = None,
) -> BaseTree:
    """Build a Tree (or UninitializedTree) describing a collection's shape.

    ``collection_type_description`` controls the depth of the tree:
    elements below ``leaf_subcollection_type`` are treated as leaves.
    """
    if leaf_subcollection_type:
        if not collection_type_description.can_map_over(leaf_subcollection_type):
            # The described collection IS the leaf subcollection (no deeper
            # structure to strip). Don't enumerate its elements; just record
            # the type so multiply() can combine it with the mapping structure.
            return UninitializedTree(
                collection_type_description.collection_type_description_factory.for_collection_type(
                    leaf_subcollection_type
                )
            )
        # Strip the leaf type from the description so it becomes a leaf
        # in the resulting tree. E.g. "list:paired" with
        # leaf_subcollection_type="paired" → description becomes "list".
        collection_type_description = collection_type_description.effective_collection_type_description(
            leaf_subcollection_type
        )
    return Tree.for_dataset_collection(collection, collection_type_description)
