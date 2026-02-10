<script setup lang="ts">
import { faArrowLeft, faSave, faSpinner } from "@fortawesome/free-solid-svg-icons";
import { FontAwesomeIcon } from "@fortawesome/vue-fontawesome";
import { BAlert, BButton } from "bootstrap-vue";
import { computed, onMounted, onUnmounted, watch } from "vue";
import { useRouter } from "vue-router/composables";

import { useHistoryNotebookStore } from "@/stores/historyNotebookStore";
import { useHistoryStore } from "@/stores/historyStore";

import HistoryNotebookEditor from "./HistoryNotebookEditor.vue";
import HistoryNotebookList from "./HistoryNotebookList.vue";

const props = defineProps<{
    historyId: string;
    notebookId?: string;
}>();

const router = useRouter();
const store = useHistoryNotebookStore();
const historyStore = useHistoryStore();

const historyName = computed(() => {
    const history = historyStore.getHistoryById(props.historyId);
    return history?.name || "History";
});

onMounted(async () => {
    await store.loadNotebooks(props.historyId);
    if (props.notebookId) {
        await store.loadNotebook(props.notebookId);
    }
});

onUnmounted(() => {
    store.$reset();
});

watch(
    () => props.historyId,
    async (newId) => {
        await store.loadNotebooks(newId);
        if (props.notebookId) {
            await store.loadNotebook(props.notebookId);
        }
    },
);

watch(
    () => props.notebookId,
    async (newId) => {
        if (newId) {
            await store.loadNotebook(newId);
        } else {
            store.clearCurrentNotebook();
        }
    },
);

function handleSelect(notebookId: string) {
    router.push(`/histories/${props.historyId}/notebooks/${notebookId}`);
}

async function handleCreate() {
    const notebook = await store.createNotebook({ title: "Untitled Notebook" });
    if (notebook) {
        router.push(`/histories/${props.historyId}/notebooks/${notebook.id}`);
    }
}

function handleBack() {
    store.clearCurrentNotebook();
    router.push(`/histories/${props.historyId}/notebooks`);
}

async function handleSave() {
    await store.saveNotebook();
}
</script>

<template>
    <div class="history-notebook-view d-flex flex-column h-100">
        <BAlert v-if="store.isLoadingList" variant="info" show>
            <FontAwesomeIcon :icon="faSpinner" spin />
            Loading notebooks...
        </BAlert>

        <BAlert v-else-if="store.error" variant="danger" show dismissible @dismissed="store.error = null">
            {{ store.error }}
        </BAlert>

        <template v-else-if="!notebookId">
            <HistoryNotebookList :notebooks="store.notebooks" @select="handleSelect" @create="handleCreate" />
        </template>

        <template v-else-if="store.hasCurrentNotebook">
            <div class="notebook-toolbar d-flex align-items-center p-2 border-bottom">
                <BButton variant="link" size="sm" @click="handleBack">
                    <FontAwesomeIcon :icon="faArrowLeft" />
                    Back
                </BButton>
                <span class="flex-grow-1 text-center font-weight-bold">
                    {{ store.currentTitle || "Untitled Notebook" }}
                </span>
                <BButton variant="primary" size="sm" :disabled="!store.canSave" @click="handleSave">
                    <FontAwesomeIcon :icon="store.isSaving ? faSpinner : faSave" :spin="store.isSaving" />
                    Save
                </BButton>
                <span v-if="store.isDirty" class="ml-2 text-warning small"> Unsaved </span>
            </div>

            <div class="notebook-content flex-grow-1 overflow-auto">
                <HistoryNotebookEditor
                    :history-id="historyId"
                    :content="store.currentContent"
                    @update:content="store.updateContent" />
            </div>
        </template>

        <BAlert v-else-if="store.isLoadingNotebook" variant="info" show>
            <FontAwesomeIcon :icon="faSpinner" spin />
            Loading notebook...
        </BAlert>
    </div>
</template>

<style scoped>
.history-notebook-view {
    background: var(--body-bg);
}
.notebook-toolbar {
    background: var(--panel-header-bg);
}
.notebook-content {
    padding: 1rem;
}
</style>
