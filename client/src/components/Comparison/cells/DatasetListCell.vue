<script setup lang="ts">
import { computed } from "vue";

import type { ComparisonRow, DatasetListCell } from "@/api/comparisons";
import { useUid } from "@/composables/utils/uid";

import type { CellDisplay } from "../comparisonUtils";

import ComparisonCell from "./ComparisonCell.vue";
import GPopover from "@/components/BaseComponents/GPopover.vue";

const props = defineProps<{
    cell: DatasetListCell;
    row: Pick<ComparisonRow, "version" | "tool_version">;
    display: CellDisplay;
    requestedMetadata?: string[];
    loading?: boolean;
}>();

// Page-unique, so the same list can appear in many rows.
const targetId = useUid("dataset-list-more-");
const more = computed(() => props.cell.items.length - 1);
</script>

<template>
    <span class="comparison-dataset-list">
        <ComparisonCell
            :cell="cell.items[0]"
            :row="row"
            :display="display"
            :requested-metadata="requestedMetadata"
            :loading="loading" />
        <template v-if="more > 0">
            <button
                :id="targetId"
                type="button"
                class="comparison-dataset-list-more btn btn-link p-0 ml-1 align-baseline"
                aria-haspopup="dialog">
                +{{ more }} more
            </button>
            <GPopover
                interactive
                :aria-label="`All ${cell.items.length} datasets`"
                :target="targetId"
                triggers="hover focus"
                boundary="window"
                placement="right">
                <ol class="comparison-dataset-list-items mb-0 pl-3">
                    <li v-for="(item, index) in cell.items" :key="index">
                        <ComparisonCell
                            :cell="item"
                            :row="row"
                            :display="display"
                            :requested-metadata="requestedMetadata"
                            :loading="loading" />
                    </li>
                </ol>
            </GPopover>
        </template>
    </span>
</template>
