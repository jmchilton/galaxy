import { defineStore } from "pinia";
import { computed, ref } from "vue";

import {
    createHistoryNotebook,
    type CreateNotebookPayload,
    deleteHistoryNotebook,
    fetchHistoryNotebook,
    fetchHistoryNotebooks,
    fetchNotebookRevision,
    fetchNotebookRevisions,
    type HistoryNotebookDetails,
    type HistoryNotebookRevisionDetails,
    type HistoryNotebookRevisionSummary,
    type HistoryNotebookSummary,
    revertNotebookRevision,
    updateHistoryNotebook,
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

    // Revision state
    const revisions = ref<HistoryNotebookRevisionSummary[]>([]);
    const selectedRevision = ref<HistoryNotebookRevisionDetails | null>(null);
    const isLoadingRevisions = ref(false);
    const isLoadingRevision = ref(false);
    const isReverting = ref(false);
    const showRevisions = ref(false);

    const hasNotebooks = computed(() => notebooks.value.length > 0);
    const hasCurrentNotebook = computed(() => currentNotebook.value !== null);
    const isDirty = computed(() => currentContent.value !== originalContent.value);
    const canSave = computed(() => isDirty.value && !isSaving.value);
    const revisionCount = computed(() => revisions.value.length);
    const hasRevisions = computed(() => revisions.value.length > 1);

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
            // Use currentContent (what the user typed) as the baseline, not data.content
            // which may be transformed by rewrite_content_for_export for rendering.
            originalContent.value = currentContent.value;
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
        clearRevisionState();
    }

    // --- Revision actions ---

    async function loadRevisions() {
        if (!historyId.value || !currentNotebook.value) {
            return;
        }
        isLoadingRevisions.value = true;
        try {
            revisions.value = await fetchNotebookRevisions(historyId.value, currentNotebook.value.id);
        } catch (e: any) {
            error.value = e.message || "Failed to load revisions";
        } finally {
            isLoadingRevisions.value = false;
        }
    }

    async function loadRevision(revisionId: string) {
        if (!historyId.value || !currentNotebook.value) {
            return;
        }
        isLoadingRevision.value = true;
        try {
            selectedRevision.value = await fetchNotebookRevision(historyId.value, currentNotebook.value.id, revisionId);
        } catch (e: any) {
            error.value = e.message || "Failed to load revision";
        } finally {
            isLoadingRevision.value = false;
        }
    }

    async function restoreRevision(revisionId: string) {
        if (!historyId.value || !currentNotebook.value) {
            return;
        }
        isReverting.value = true;
        try {
            const data = await revertNotebookRevision(historyId.value, currentNotebook.value.id, revisionId);
            currentNotebook.value = data;
            originalContent.value = data.content || "";
            currentContent.value = data.content || "";
            selectedRevision.value = null;
            showRevisions.value = false;
            await loadRevisions();
        } catch (e: any) {
            error.value = e.message || "Failed to restore revision";
        } finally {
            isReverting.value = false;
        }
    }

    function toggleRevisions() {
        showRevisions.value = !showRevisions.value;
        if (showRevisions.value) {
            loadRevisions();
        } else {
            selectedRevision.value = null;
        }
    }

    function clearSelectedRevision() {
        selectedRevision.value = null;
    }

    function clearRevisionState() {
        revisions.value = [];
        selectedRevision.value = null;
        isLoadingRevisions.value = false;
        isLoadingRevision.value = false;
        isReverting.value = false;
        showRevisions.value = false;
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
        clearRevisionState();
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
        // Revision state
        revisions,
        selectedRevision,
        isLoadingRevisions,
        isLoadingRevision,
        isReverting,
        showRevisions,
        revisionCount,
        hasRevisions,
        // Revision actions
        loadRevisions,
        loadRevision,
        restoreRevision,
        toggleRevisions,
        clearSelectedRevision,
        $reset,
    };
});
