<script setup lang="ts">
import { computed, ref } from "vue";
import { useRoute, useRouter } from "vue-router/composables";

import type { HistorySummary } from "@/api";

import HistoryScrollList from "@/components/History/HistoryScrollList.vue";
import ActivityPanel from "./ActivityPanel.vue";

const route = useRoute();
const router = useRouter();

// HistoryScrollList expects a filter string and a loading flag; we don't expose
// a search box here (the panel mirrors the Workflow Invocations one), so the
// filter stays empty.
const filter = ref("");
const loading = ref(false);

// Highlight the row whose graph is currently open in the centre panel — the
// route's `historyId` param when sitting on /histories/:historyId/graph.
const selectedHistories = computed(() => {
    const id = route.params.historyId as string | undefined;
    return id ? [{ id }] : [];
});

function openGraph(history: HistorySummary) {
    router.push(`/histories/${history.id}/graph`);
}
</script>

<template>
    <ActivityPanel title="History Graphs">
        <HistoryScrollList
            :filter="filter"
            :loading.sync="loading"
            :selected-histories="selectedHistories"
            @selectHistory="openGraph" />
    </ActivityPanel>
</template>
