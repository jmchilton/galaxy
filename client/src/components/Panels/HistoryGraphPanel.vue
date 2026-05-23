<script setup lang="ts">
import { storeToRefs } from "pinia";
import { computed, ref } from "vue";
import { useRoute, useRouter } from "vue-router/composables";

import type { HistorySummary } from "@/api";
import { HistoriesFilters } from "@/components/History/HistoriesFilters";
import { useHistoryStore } from "@/stores/historyStore";

import FilterMenu from "@/components/Common/FilterMenu.vue";
import HistoryScrollList from "@/components/History/HistoryScrollList.vue";
import ActivityPanel from "./ActivityPanel.vue";

const route = useRoute();
const router = useRouter();

const filter = ref("");
const showAdvanced = ref(false);
const loading = ref(false);

const { historiesLoading } = storeToRefs(useHistoryStore());

// Highlight the row whose graph is currently open in the centre panel — the
// route's `historyId` param when sitting on /histories/:historyId/graph.
const selectedHistories = computed(() => {
    const id = route.params.historyId as string | undefined;
    return id ? [{ id }] : [];
});

function setFilter(newFilter: string, newValue: string) {
    filter.value = HistoriesFilters.setFilterValue(filter.value, newFilter, newValue);
}

function openGraph(history: HistorySummary) {
    router.push(`/histories/${history.id}/graph`);
}
</script>

<template>
    <ActivityPanel title="History Graphs">
        <template v-slot:header>
            <FilterMenu
                name="Histories"
                placeholder="search histories"
                :filter-class="HistoriesFilters"
                :filter-text.sync="filter"
                :loading="historiesLoading || loading"
                :show-advanced.sync="showAdvanced" />
        </template>
        <HistoryScrollList
            v-show="!showAdvanced"
            :filter="filter"
            :loading.sync="loading"
            :selected-histories="selectedHistories"
            @setFilter="setFilter"
            @selectHistory="openGraph" />
    </ActivityPanel>
</template>
