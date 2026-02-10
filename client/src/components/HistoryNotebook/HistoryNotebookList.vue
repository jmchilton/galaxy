<script setup lang="ts">
import { faChevronRight, faPlus } from "@fortawesome/free-solid-svg-icons";
import { FontAwesomeIcon } from "@fortawesome/vue-fontawesome";
import { BButton } from "bootstrap-vue";

import type { HistoryNotebookSummary } from "@/api/historyNotebooks";

defineProps<{
    notebooks: HistoryNotebookSummary[];
}>();

defineEmits<{
    (e: "select", notebookId: string): void;
    (e: "create"): void;
}>();

function getNotebookTitle(notebook: HistoryNotebookSummary): string {
    return notebook.title || "Untitled Notebook";
}

function formatDate(dateStr: string): string {
    return new Date(dateStr).toLocaleDateString(undefined, {
        month: "short",
        day: "numeric",
        hour: "2-digit",
        minute: "2-digit",
    });
}
</script>

<template>
    <div class="history-notebook-list">
        <div class="list-header d-flex justify-content-between align-items-center p-3 border-bottom">
            <h4 class="mb-0">Notebooks</h4>
            <BButton variant="primary" size="sm" @click="$emit('create')">
                <FontAwesomeIcon :icon="faPlus" />
                New Notebook
            </BButton>
        </div>

        <div v-if="notebooks.length === 0" class="empty-state text-center p-4">
            <p class="text-muted">No notebooks yet</p>
            <p class="text-muted small">
                Create a notebook to document your analysis with rich markdown, embedded datasets, and visualizations.
            </p>
        </div>

        <div v-else class="notebook-items">
            <div
                v-for="notebook in notebooks"
                :key="notebook.id"
                class="notebook-item p-3 border-bottom cursor-pointer"
                @click="$emit('select', notebook.id)">
                <div class="d-flex justify-content-between align-items-start">
                    <div>
                        <div class="notebook-title fw-bold">
                            {{ getNotebookTitle(notebook) }}
                        </div>
                        <div class="notebook-meta text-muted small">Updated {{ formatDate(notebook.update_time) }}</div>
                    </div>
                    <FontAwesomeIcon :icon="faChevronRight" class="text-muted" />
                </div>
            </div>
        </div>
    </div>
</template>

<style scoped>
.notebook-item:hover {
    background: var(--panel-header-bg);
}
.cursor-pointer {
    cursor: pointer;
}
</style>
