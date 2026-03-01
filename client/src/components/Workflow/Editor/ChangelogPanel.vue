<script setup lang="ts">
import { BButton } from "bootstrap-vue";
import { onMounted, ref, watch } from "vue";

import { type ChangelogEntry, getChangelog } from "@/api/workflows";
import { errorMessageAsString } from "@/utils/simple-error";

import LoadingSpan from "@/components/LoadingSpan.vue";
import ActivityPanel from "@/components/Panels/ActivityPanel.vue";
import UtcDate from "@/components/UtcDate.vue";

const props = defineProps<{
    workflowId: string;
}>();

const emit = defineEmits<{
    (e: "revert", entry: ChangelogEntry): void;
}>();

const entries = ref<ChangelogEntry[]>([]);
const loading = ref(false);
const totalMatches = ref(0);
const currentOffset = ref(0);
const pageSize = 25;
const error = ref<string | null>(null);

const hasMore = ref(false);

async function fetchChangelog(offset = 0) {
    loading.value = true;
    error.value = null;

    try {
        const result = await getChangelog(props.workflowId, pageSize, offset);
        if (offset === 0) {
            entries.value = result.data;
        } else {
            entries.value = [...entries.value, ...result.data];
        }
        totalMatches.value = result.totalMatches;
        currentOffset.value = offset + result.data.length;
        hasMore.value = currentOffset.value < totalMatches.value;
    } catch (e) {
        error.value = errorMessageAsString(e);
    } finally {
        loading.value = false;
    }
}

function loadMore() {
    fetchChangelog(currentOffset.value);
}

function refresh() {
    currentOffset.value = 0;
    fetchChangelog(0);
}

onMounted(() => {
    fetchChangelog();
});

watch(
    () => props.workflowId,
    () => {
        refresh();
    },
);

defineExpose({ refresh });
</script>

<template>
    <ActivityPanel title="Changelog">
        <template v-slot:header-buttons>
            <BButton title="Refresh" variant="link" size="sm" @click="refresh"> Refresh </BButton>
        </template>

        <div v-if="loading && entries.length === 0">
            <LoadingSpan message="Loading changelog" />
        </div>

        <div v-else-if="error" class="alert alert-danger m-2">{{ error }}</div>

        <div v-else-if="entries.length === 0" class="text-muted p-2">
            No changelog entries yet. Save changes to create entries.
        </div>

        <div v-else class="changelog-list">
            <div v-for="entry in entries" :key="entry.id" class="changelog-entry">
                <div class="entry-header">
                    <span class="entry-title">{{ entry.title }}</span>
                    <UtcDate :date="entry.create_time" mode="elapsed" class="entry-time" />
                </div>

                <span v-if="entry.is_revert" class="badge badge-warning entry-badge"> revert </span>

                <BButton
                    size="sm"
                    variant="outline-secondary"
                    class="entry-revert-btn"
                    title="Revert to the state before this change"
                    @click="emit('revert', entry)">
                    Revert to before this
                </BButton>
            </div>

            <BButton v-if="hasMore" variant="link" :disabled="loading" class="load-more-btn" @click="loadMore">
                Load more...
            </BButton>
        </div>
    </ActivityPanel>
</template>

<style scoped lang="scss">
@import "@/style/scss/theme/blue.scss";

.changelog-list {
    display: flex;
    flex-direction: column;
    overflow-y: auto;
    flex: 1;
}

.changelog-entry {
    padding: 0.5rem 0.75rem;
    border-bottom: 1px solid $border-color;

    &:last-child {
        border-bottom: none;
    }
}

.entry-header {
    display: flex;
    flex-direction: column;
    margin-bottom: 0.25rem;
}

.entry-title {
    font-weight: 500;
    font-size: 0.9rem;
    line-height: 1.3;
}

.entry-time {
    font-size: 0.8rem;
    color: $text-muted;
}

.entry-badge {
    font-size: 0.75rem;
    margin-bottom: 0.25rem;
    display: inline-block;
}

.entry-revert-btn {
    margin-top: 0.25rem;
    font-size: 0.8rem;
}

.load-more-btn {
    align-self: center;
    margin: 0.5rem 0;
}
</style>
