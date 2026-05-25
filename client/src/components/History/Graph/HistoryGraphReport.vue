<script setup lang="ts">
import { BAlert } from "bootstrap-vue";
import { computed, onMounted, ref } from "vue";

import { GalaxyApi } from "@/api";
import { useMarkdown } from "@/composables/markdown";
import { errorMessageAsString } from "@/utils/simple-error";

import LoadingSpan from "@/components/LoadingSpan.vue";

interface Props {
    historyId: string;
}

const props = defineProps<Props>();

const { renderMarkdown } = useMarkdown({ openLinksInNewPage: true });

// Comprehensive history-wide AI analysis report. Generated when the tab is
// first opened — the component only mounts while the AI Summary tab is active.
const reportLoading = ref(false);
const reportError = ref<string | null>(null);
const report = ref<string | null>(null);

async function loadReport() {
    reportLoading.value = true;
    reportError.value = null;
    try {
        const { data, error, response } = await GalaxyApi().POST("/api/ai/agents/history-summary", {
            body: { history_id: props.historyId },
        });
        if (!response.ok) {
            reportError.value = errorMessageAsString(error, `Request failed with status ${response.status}.`);
            return;
        }
        report.value = data?.content ?? "";
    } catch (e) {
        reportError.value = errorMessageAsString(e, "Failed to generate report.");
    } finally {
        reportLoading.value = false;
    }
}

onMounted(loadReport);

const reportHtml = computed(() => (report.value ? renderMarkdown(report.value) : ""));
</script>

<template>
    <div class="history-graph-report p-2">
        <LoadingSpan v-if="reportLoading" message="Generating history summary" />
        <BAlert v-else-if="reportError" variant="danger" show class="mb-0">
            Failed to generate the AI summary: {{ reportError }}
        </BAlert>
        <!-- eslint-disable-next-line vue/no-v-html — markdown is sanitised by useMarkdown -->
        <div v-else-if="report" class="report-text" v-html="reportHtml" />
        <BAlert v-else show variant="info" class="mb-0">No summary available.</BAlert>
    </div>
</template>

<style lang="scss" scoped>
.report-text {
    font-size: 0.9rem;
    line-height: 1.4;

    :deep(h2) {
        font-size: 1rem;
        font-weight: 600;
        margin-top: 0.75rem;
        margin-bottom: 0.25rem;
    }
    :deep(p) {
        margin-bottom: 0.5rem;
    }
    :deep(ul),
    :deep(ol) {
        margin-bottom: 0.5rem;
        padding-left: 1.25rem;
    }
    :deep(code) {
        font-size: 0.85em;
    }
}
</style>
