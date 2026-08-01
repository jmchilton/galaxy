<!-- When a dataset collection is being viewed, this panel shows the contents of that collection -->

<script setup lang="ts">
import { computed, ref, watch } from "vue";

import {
    canMutateHistory,
    type CollectionElementDataset,
    type CollectionEntry,
    type DCESummary,
    type HDADetailed,
    type HDCASummary,
    type HistorySummary,
    isCollectionElement,
    isDatasetElement,
    isDCE,
    isHDCA,
    type SubCollection,
} from "@/api";
import { fetchDatasetDetails } from "@/api/datasets";
import ExpandedItems from "@/components/History/Content/ExpandedItems";
import { itemUniqueKey } from "@/components/History/Content/model/itemKey";
import { HistoryFilters } from "@/components/History/HistoryFilters";
import { updateContentFields } from "@/components/History/model/queries";
import { useSelectedItems } from "@/composables/selectedItems/selectedItems";
import { useCollectionElementsStore } from "@/stores/collectionElementsStore";
import { setItemDragstart } from "@/utils/setDrag";
import { errorMessageAsString } from "@/utils/simple-error";

import CollectionDetails from "./CollectionDetails.vue";
import CollectionNavigation from "./CollectionNavigation.vue";
import CollectionOperations from "./CollectionOperations.vue";
import Alert from "@/components/Alert.vue";
import CollectionCreatorIndex from "@/components/Collections/CollectionCreatorIndex.vue";
import ContentItem from "@/components/History/Content/ContentItem.vue";
import ListingLayout from "@/components/History/Layout/ListingLayout.vue";

interface Props {
    history: HistorySummary;
    selectedCollections: CollectionEntry[];
    showControls?: boolean;
    filterable?: boolean;
    multiView?: boolean;
}

const props = withDefaults(defineProps<Props>(), {
    showControls: true,
    filterable: false,
});

const collectionElementsStore = useCollectionElementsStore();

const emit = defineEmits<{
    (e: "view-collection", collection: CollectionEntry): void;
    (e: "update:selected-collections", collections: CollectionEntry[]): void;
}>();

const offset = ref(0);

const dsc = computed(() => {
    const currentCollection = props.selectedCollections[props.selectedCollections.length - 1];
    if (currentCollection === undefined) {
        throw new Error("No collection selected");
    }
    return currentCollection as HDCASummary;
});
watch(
    () => [dsc.value, offset.value],
    () => {
        collectionElementsStore.fetchMissingElements(dsc.value, offset.value);
    },
    { immediate: true },
);

const collectionElements = computed(() => collectionElementsStore.getCollectionElements(dsc.value) ?? []);
const loading = computed(() => collectionElementsStore.isLoadingCollectionElements(dsc.value));
const error = computed(() => collectionElementsStore.getLoadingCollectionElementsError(dsc.value));
const jobState = computed(() => ("job_state_summary" in dsc.value ? dsc.value.job_state_summary : undefined));
const populatedStateMsg = computed(() =>
    "populated_state_message" in dsc.value ? dsc.value.populated_state_message : undefined,
);
const rootCollection = computed(() => {
    if (isHDCA(props.selectedCollections[0])) {
        return props.selectedCollections[0];
    } else {
        throw new Error("Root collection must be an HistoryDatasetCollectionAssociation");
    }
});
const isRoot = computed(() => dsc.value == rootCollection.value);
const canEdit = computed(() => isRoot.value && canMutateHistory(props.history));

/** Selection inside a collection uses the same composable as the history
 * panel, so selecting behaves identically in both places: a select toggle,
 * click to select without opening the item, and shift for a range. */
const showCollectionCreator = ref(false);

/** The datasets behind this collection's elements, in listing order.
 *
 * These are the store's own objects — the same ones handed to `ContentItem` as `item`,
 * which is what it passes back to the click handler. Deriving copies here instead would
 * give a row two identities, and the composable's range selection is positional
 * (`allItems.indexOf(item)`), so it would stop finding the clicked row.
 */
const selectableDatasets = computed(() =>
    collectionElements.value
        .filter(isDCE)
        .filter(isDatasetElement)
        .map((element) => element.object),
);

const {
    selectedItems,
    showSelection,
    selectionSize,
    setShowSelection,
    isRangeSelectAnchor,
    isSelected,
    setSelected,
    initKeySelection,
    itemRefs,
    onClick: onSelectClick,
    onKeyDown: onSelectKeyDown,
} = useSelectedItems<CollectionElementDataset, typeof ContentItem>({
    scopeKey: computed(() => String(dsc.value?.id ?? "")),
    getItemKey: itemUniqueKey,
    allItems: selectableDatasets,
    selectable: computed(() => canEdit.value),
    expectedKeyDownClass: "content-item",
    // Matches the history panel so keyboard navigation behaves the same.
    disallowedKeyDownClasses: ["sub-item"],
    // A collection listing has no filtering and no query selection, so these
    // are inert; they exist because the composable is shared with the history
    // panel, where filtering drives select-all-in-query.
    filterText: ref(""),
    totalItemsInQuery: computed(() => selectableDatasets.value.length),
    filterClass: HistoryFilters,
    // Deleting an element from a collection is not offered here.
    onDelete: () => {},
});

/** The datasets the collection creator was opened with, hydrated from `selectedItems`. */
const selectedDatasets = ref<HDADetailed[]>([]);
const loadingSelection = ref(false);
const selectionError = ref<string | null>(null);

/** A collection element carries less than the builders need: the contents API serializes
 * it through `dictify_element_reference`, which omits `extension`, `hid`, `deleted` and
 * `visible`. Without them the builder's mixed-extension warning can never fire, its
 * messages read "undefined: <name>", and deleted elements are not rejected. So fetch the
 * real dataset for each selected element before handing the selection over.
 *
 * `CollectionCreatorIndex`'s own hydration watcher cannot do this: it fills gaps from
 * `historyDatasetsStore`, which fetches with `visible: true`, and collection elements are
 * hidden. */
async function onBuildCollection() {
    loadingSelection.value = true;
    selectionError.value = null;
    try {
        selectedDatasets.value = await Promise.all(
            Array.from(selectedItems.value.values()).map((dataset) => fetchDatasetDetails({ id: dataset.id })),
        );
        showCollectionCreator.value = true;
    } catch (e) {
        selectionError.value = errorMessageAsString(e);
    } finally {
        loadingSelection.value = false;
    }
}

function onCreatedCollection() {
    // `watch(showSelection)` in the composable resets the selection when it is hidden.
    setShowSelection(false);
    selectedDatasets.value = [];
    showCollectionCreator.value = false;
}

/** `ContentItem` has already persisted the change; reflect it on the stored element so the
 * row keeps showing it. Mirrors the history panel's handler. */
function onTagChange(item: CollectionElementDataset, newTags: string[]) {
    item.tags = newTags;
}

async function updateDsc(collection: CollectionEntry, fields: Object | undefined) {
    if (!isHDCA(collection)) {
        return;
    }
    const updatedCollection = await updateContentFields(collection, fields);
    // Update only editable fields
    collection.name = updatedCollection.name || collection.name;
    collection.tags = updatedCollection.tags || collection.tags;
}

function getItemKey(item: DCESummary) {
    return `${item.element_type}-${item.id}`;
}

function onScroll(newOffset: number) {
    offset.value = newOffset;
}

async function onViewDatasetCollectionElement(element: DCESummary) {
    if (!isCollectionElement(element)) {
        return;
    }
    offset.value = 0;
    const collection: SubCollection = {
        ...element.object,
        name: element.element_identifier,
        hdca_id: rootCollection.value.id,
    };
    emit("view-collection", collection);
}

watch(
    () => props.history,
    (newHistory, oldHistory) => {
        if (newHistory.id != oldHistory.id) {
            // Send up event closing out selected collection on history change.
            emit("update:selected-collections", []);
        }
    },
);

watch(
    jobState,
    () => {
        collectionElementsStore.invalidateCollectionElements(dsc.value);
        collectionElementsStore.fetchMissingElements(dsc.value, offset.value);
    },
    { deep: true },
);
</script>

<template>
    <Alert v-if="error" variant="error">
        {{ errorMessageAsString(error) }}
    </Alert>
    <ExpandedItems v-else v-slot="{ isExpanded, setExpanded }" :scope-key="dsc.id" :get-item-key="getItemKey">
        <section class="dataset-collection-panel w-100 d-flex flex-column" :class="{ 'compact-panel': multiView }">
            <section>
                <CollectionNavigation
                    :history-name="history.name"
                    :selected-collections="selectedCollections"
                    v-on="$listeners" />
                <CollectionDetails :dsc="dsc" :writeable="canEdit" @update:dsc="updateDsc(dsc, $event)" />
                <CollectionOperations
                    v-if="canEdit && showControls"
                    :dsc="dsc"
                    :show-selection="showSelection"
                    :selection-size="selectionSize"
                    :building-collection="loadingSelection"
                    @update:show-selection="setShowSelection"
                    @build-collection="onBuildCollection" />
            </section>
            <section class="position-relative flex-grow-1 scroller">
                <div>
                    <b-alert v-if="selectionError" class="m-2" variant="danger" show>
                        {{ selectionError }}
                    </b-alert>
                    <b-alert
                        v-if="collectionElements.length === 0"
                        class="m-2"
                        :variant="populatedStateMsg ? 'danger' : 'info'"
                        show>
                        {{ populatedStateMsg || "This is an empty collection." }}
                    </b-alert>
                    <ListingLayout
                        v-else
                        data-key="element_index"
                        :items="collectionElements"
                        :loading="loading"
                        @scroll="onScroll">
                        <template v-slot:item="{ item }">
                            <ContentItem
                                v-if="item.id === undefined"
                                :id="item.element_index + 1"
                                :item="item"
                                :is-placeholder="true"
                                name="Loading..." />
                            <!-- A dataset row is selectable and taggable; every selection
                                 binding uses `item.object`, the one object identity the row
                                 has, which is also what ContentItem hands back to the click
                                 handler. -->
                            <ContentItem
                                v-else-if="isDatasetElement(item)"
                                :id="item.element_index + 1"
                                :ref="itemRefs[itemUniqueKey(item.object)]"
                                :item="item.object"
                                :name="item.element_identifier"
                                taggable
                                :writable="canEdit"
                                :expand-dataset="isExpanded(item)"
                                :selectable="showSelection"
                                :selected="isSelected(item.object)"
                                :is-range-select-anchor="isRangeSelectAnchor(item.object)"
                                :select-click-handler="onSelectClick"
                                :filterable="filterable"
                                @update:selected="setSelected(item.object, $event)"
                                @init-key-selection="initKeySelection"
                                @on-key-down="onSelectKeyDown(item.object, $event)"
                                @tag-change="onTagChange"
                                @drag-start="setItemDragstart(item, $event)"
                                @update:expand-dataset="setExpanded(item, $event)" />
                            <!-- A sub-collection row is neither selectable nor taggable; it
                                 drills down instead. -->
                            <ContentItem
                                v-else
                                :id="item.element_index + 1"
                                :item="item.object"
                                :name="item.element_identifier"
                                :is-dataset="false"
                                :expand-dataset="isExpanded(item)"
                                :filterable="filterable"
                                @drag-start="setItemDragstart(item, $event)"
                                @update:expand-dataset="setExpanded(item, $event)"
                                @view-collection="onViewDatasetCollectionElement(item)" />
                        </template>
                    </ListingLayout>

                    <CollectionCreatorIndex
                        v-if="showCollectionCreator"
                        :history-id="history.id"
                        collection-type="list"
                        :extended-collection-type="{}"
                        :selected-items="selectedDatasets"
                        :show.sync="showCollectionCreator"
                        hide-on-create
                        @created-collection="onCreatedCollection" />
                </div>
            </section>
        </section>
    </ExpandedItems>
</template>

<style scoped>
.compact-panel {
    max-width: 15rem;
}
</style>
