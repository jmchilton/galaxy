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
import ExpandedItems from "@/components/History/Content/ExpandedItems";
import { itemUniqueKey } from "@/components/History/Content/model/itemKey";
import { HistoryFilters } from "@/components/History/HistoryFilters";
import { updateContentFields } from "@/components/History/model/queries";
import { useSelectedItems } from "@/composables/selectedItems/selectedItems";
import { useCollectionElementsStore } from "@/stores/collectionElementsStore";
import { useDatasetStore } from "@/stores/datasetStore";
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
const datasetStore = useDatasetStore();

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

const showCollectionCreator = ref(false);

/** The datasets behind this collection's elements, in listing order.
 *
 * These must be the store's own objects, the same ones bound to `ContentItem`'s `item`:
 * range selection is positional (`allItems.indexOf(item)`), so a row deriving a second
 * identity here would stop being found.
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
    disallowedKeyDownClasses: ["sub-item"],
    // A collection listing has no filtering and no select-all-in-query, so these are inert.
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

/** The contents API serves a minimal element payload, without the `extension`, `hid`,
 * `deleted` and `visible` the collection builders read, so expand the selection before
 * handing it over. `datasetStore` also backs the row's expanded details view, so a row the
 * user already opened is a cache hit.
 *
 * `CollectionCreatorIndex`'s own hydration watcher cannot do this: it fills gaps from
 * `historyDatasetsStore`, which fetches with `visible: true`, and collection elements are
 * hidden. */
async function onBuildCollection() {
    loadingSelection.value = true;
    selectionError.value = null;
    const ids = Array.from(selectedItems.value.values()).map((dataset) => dataset.id);
    const datasets = await Promise.all(ids.map((id) => datasetStore.fetchDataset({ id })));
    loadingSelection.value = false;

    const failedId = ids.find((id, index) => datasets[index] === undefined);
    if (failedId !== undefined) {
        selectionError.value = errorMessageAsString(datasetStore.getDatasetError(failedId));
        return;
    }
    selectedDatasets.value = datasets as HDADetailed[];
    showCollectionCreator.value = true;
}

function onCreatedCollection() {
    // `watch(showSelection)` in the composable resets the selection when it is hidden.
    setShowSelection(false);
    selectedDatasets.value = [];
    showCollectionCreator.value = false;
}

/** `ContentItem` has already persisted the change; reflect it on the stored element so the
 * row keeps showing it. */
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
                            <!-- Every binding here uses `item.object`, the row's single
                                 identity, which ContentItem hands back to the click handler. -->
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
                            <!-- A sub-collection row drills down rather than selecting. -->
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
