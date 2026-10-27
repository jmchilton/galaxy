<script setup lang="ts">
import { computed } from "vue";

import type { ComparisonCell, ComparisonRow } from "@/api/comparisons";

import { type CellDisplay, metadataKeyOf } from "../comparisonUtils";

import ItemCell from "./ItemCell.vue";
import MetadataCell from "./MetadataCell.vue";
import MissingCell from "./MissingCell.vue";
import ValueCell from "./ValueCell.vue";
import ItemPopoverLink from "@/components/Common/ItemPopoverLink.vue";

const props = defineProps<{
    cell?: ComparisonCell;
    row: Pick<ComparisonRow, "version" | "tool_version">;
    display: CellDisplay;
    /** Metadata elements the loaded table was fetched with. */
    requestedMetadata?: string[];
}>();

const metadataElement = computed(() => metadataKeyOf(props.display));
</script>

<template>
    <span v-if="!cell" class="text-muted" title="No cell for this run">&mdash;</span>
    <MissingCell v-else-if="cell.type === 'missing'" :cell="cell" :row="row" />
    <template v-else-if="cell.type === 'value'">
        <ItemPopoverLink v-if="display === 'link' && cell.dataset_id" :item-id="cell.dataset_id">
            <ValueCell :value="cell.value" />
        </ItemPopoverLink>
        <ValueCell v-else :value="cell.value" />
    </template>
    <MetadataCell
        v-else-if="metadataElement"
        :cell="cell"
        :element="metadataElement"
        :requested="Boolean(requestedMetadata?.includes(metadataElement))" />
    <ItemCell v-else :cell="cell" />
</template>
