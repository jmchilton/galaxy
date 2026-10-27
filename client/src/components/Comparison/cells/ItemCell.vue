<script setup lang="ts">
import { faLayerGroup } from "@fortawesome/free-solid-svg-icons";
import { FontAwesomeIcon } from "@fortawesome/vue-fontawesome";
import { computed } from "vue";

import type { CollectionCell, DatasetCell } from "@/api/comparisons";
import { type GraphStepState, iconClasses } from "@/composables/useInvocationGraph";

import { historyLink } from "../comparisonTable";

import ItemPopoverLink from "@/components/Common/ItemPopoverLink.vue";

const props = defineProps<{
    cell: DatasetCell | CollectionCell;
}>();

const isCollection = computed(() => props.cell.type === "collection");
const purged = computed(() => props.cell.type === "dataset" && props.cell.purged);
// Collections have no dataset page; open their history.
const to = computed(() => (isCollection.value ? historyLink(props.cell.history_id) : undefined));
const stateIcon = computed(() => {
    const state = props.cell.type === "dataset" ? props.cell.state : props.cell.populated_state;
    return state === "ok" ? undefined : iconClasses[state as GraphStepState];
});
const stateTitle = computed(() => (props.cell.type === "dataset" ? props.cell.state : props.cell.populated_state));
</script>

<template>
    <span class="comparison-item">
        <FontAwesomeIcon
            v-if="stateIcon"
            :icon="stateIcon.icon"
            :spin="stateIcon.spin"
            :class="stateIcon.class"
            :title="stateTitle"
            fixed-width />
        <ItemPopoverLink
            :item-id="cell.id"
            :item-src="isCollection ? 'hdca' : 'hda'"
            :to="to"
            :link-class="cell.deleted ? 'comparison-item-deleted' : undefined">
            <FontAwesomeIcon v-if="isCollection" :icon="faLayerGroup" class="text-muted" title="Collection" />
            <span v-if="cell.hid !== null && cell.hid !== undefined" class="text-muted">{{ cell.hid }}:</span>
            {{ cell.name ?? cell.id }}
        </ItemPopoverLink>
        <span v-if="purged" class="badge badge-danger">purged</span>
        <span v-else-if="cell.deleted" class="badge badge-danger">deleted</span>
    </span>
</template>

<style scoped>
.comparison-item :deep(.comparison-item-deleted) {
    text-decoration: line-through;
}
</style>
