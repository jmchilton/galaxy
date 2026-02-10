import { defineStore } from "pinia";
import { computed, ref } from "vue";

import {
    createHistoryNotebook,
    deleteHistoryNotebook,
    fetchHistoryNotebook,
    fetchHistoryNotebooks,
    updateHistoryNotebook,
    type CreateNotebookPayload,
    type HistoryNotebookDetails,
    type HistoryNotebookSummary,
    type UpdateNotebookPayload,
} from "@/api/historyNotebooks";

export const useHistoryNotebookStore = defineStore("historyNotebook", () => {
    const notebooks = ref<HistoryNotebookSummary[]>([]);
    const currentNotebook = ref<HistoryNotebookDetails | null>(null);
    const originalContent = ref("");
    const currentContent = ref("");
    const currentTitle = ref("");
    const isLoadingList = ref(false);
    const isLoadingNotebook = ref(false);
    const isSaving = ref(false);
    const error = ref<string | null>(null);
    const historyId = ref<string | null>(null);

    const hasNotebooks = computed(() => notebooks.value.length > 0);
    const hasCurrentNotebook = computed(() => currentNotebook.value !== null);
    const isDirty = computed(() => currentContent.value !== originalContent.value);
    const canSave = computed(() => isDirty.value && !isSaving.value);

    async function loadNotebooks(newHistoryId: string) {
        historyId.value = newHistoryId;
        isLoadingList.value = true;
        error.value = null;
        try {
            notebooks.value = await fetchHistoryNotebooks(newHistoryId);
        } catch (e: any) {
            error.value = e.message || "Failed to load notebooks";
        } finally {
            isLoadingList.value = false;
        }
    }

    async function loadNotebook(notebookId: string) {
        if (!historyId.value) {
            return;
        }
        isLoadingNotebook.value = true;
        error.value = null;
        try {
            const data = await fetchHistoryNotebook(historyId.value, notebookId);
            currentNotebook.value = data;
            originalContent.value = data.content || "";
            currentContent.value = data.content || "";
            currentTitle.value = data.title || "";
        } catch (e: any) {
            error.value = e.message || "Failed to load notebook";
        } finally {
            isLoadingNotebook.value = false;
        }
    }

    async function createNotebook(payload?: CreateNotebookPayload): Promise<HistoryNotebookDetails | null> {
        if (!historyId.value) {
            return null;
        }
        isLoadingNotebook.value = true;
        error.value = null;
        try {
            const data = await createHistoryNotebook(historyId.value, payload || {});
            currentNotebook.value = data;
            originalContent.value = data.content || "";
            currentContent.value = data.content || "";
            currentTitle.value = data.title || "";
            await loadNotebooks(historyId.value);
            return data;
        } catch (e: any) {
            error.value = e.message || "Failed to create notebook";
            throw e;
        } finally {
            isLoadingNotebook.value = false;
        }
    }

    async function saveNotebook() {
        if (!historyId.value || !currentNotebook.value || !isDirty.value) {
            return;
        }
        isSaving.value = true;
        error.value = null;
        try {
            const payload: UpdateNotebookPayload = {
                content: currentContent.value,
                title: currentTitle.value || undefined,
            };
            const data = await updateHistoryNotebook(historyId.value, currentNotebook.value.id, payload);
            currentNotebook.value = data;
            originalContent.value = data.content || "";
        } catch (e: any) {
            error.value = e.message || "Failed to save notebook";
            throw e;
        } finally {
            isSaving.value = false;
        }
    }

    async function deleteCurrentNotebook() {
        if (!historyId.value || !currentNotebook.value) {
            return;
        }
        try {
            await deleteHistoryNotebook(historyId.value, currentNotebook.value.id);
            currentNotebook.value = null;
            originalContent.value = "";
            currentContent.value = "";
            currentTitle.value = "";
            await loadNotebooks(historyId.value);
        } catch (e: any) {
            error.value = e.message || "Failed to delete notebook";
            throw e;
        }
    }

    function updateContent(content: string) {
        currentContent.value = content;
    }

    function updateTitle(title: string) {
        currentTitle.value = title;
    }

    function discardChanges() {
        currentContent.value = originalContent.value;
    }

    function clearCurrentNotebook() {
        currentNotebook.value = null;
        originalContent.value = "";
        currentContent.value = "";
        currentTitle.value = "";
    }

    function $reset() {
        notebooks.value = [];
        currentNotebook.value = null;
        originalContent.value = "";
        currentContent.value = "";
        currentTitle.value = "";
        isLoadingList.value = false;
        isLoadingNotebook.value = false;
        isSaving.value = false;
        error.value = null;
        historyId.value = null;
    }

    return {
        notebooks,
        currentNotebook,
        currentContent,
        currentTitle,
        isLoadingList,
        isLoadingNotebook,
        isSaving,
        error,
        historyId,
        hasNotebooks,
        hasCurrentNotebook,
        isDirty,
        canSave,
        loadNotebooks,
        loadNotebook,
        createNotebook,
        saveNotebook,
        deleteCurrentNotebook,
        updateContent,
        updateTitle,
        discardChanges,
        clearCurrentNotebook,
        $reset,
    };
});
