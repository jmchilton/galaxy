<script setup lang="ts">
import { ref, computed } from "vue"
import { ToolShedApi } from "@/schema"
import type { components } from "@/schema"
import { notifyOnCatch } from "@/util"
import ChangesetSummaryTable from "./ChangesetSummaryTable.vue"
import JsonDiffViewer from "./JsonDiffViewer.vue"
import LogMessagesViewer from "./LogMessagesViewer.vue"

type ResetMetadataResponse = components["schemas"]["ResetMetadataOnRepositoryResponse"]

interface Props {
    repositoryId: string
}
const props = defineProps<Props>()
const emit = defineEmits<{
    (e: "resetComplete"): void
}>()

const loading = ref(false)
const previewResult = ref<ResetMetadataResponse | null>(null)
const viewMode = ref<"table" | "diff" | "log">("table")

const logMessages = computed(() => previewResult.value?.log_messages ?? [])
const logMessageCount = computed(() => logMessages.value.length)

type ViewMode = "table" | "diff" | "log"

const viewModeOptions = computed(() => {
    const options: Array<{ value: ViewMode; label: string }> = [
        { value: "table", label: "Summary Table" },
        { value: "diff", label: "JSON Diff" },
    ]
    if (logMessageCount.value > 0) {
        options.push({ value: "log", label: `Log (${logMessageCount.value})` })
    }
    return options
})

function handleResult(data: ResetMetadataResponse | undefined) {
    previewResult.value = data ?? null
    // Auto-switch to log tab if there are errors or warnings
    if (data?.log_messages?.some((m) => m.level === "error" || m.level === "warning")) {
        viewMode.value = "log"
    }
}

async function runPreview() {
    loading.value = true
    previewResult.value = null
    viewMode.value = "table"
    try {
        const { data } = await ToolShedApi().POST("/api/repositories/{encoded_repository_id}/reset_metadata", {
            params: {
                path: { encoded_repository_id: props.repositoryId },
                query: { dry_run: true, verbose: true },
            },
        })
        handleResult(data)
    } catch (e) {
        notifyOnCatch(e)
    } finally {
        loading.value = false
    }
}

async function applyReset() {
    loading.value = true
    try {
        const { data } = await ToolShedApi().POST("/api/repositories/{encoded_repository_id}/reset_metadata", {
            params: {
                path: { encoded_repository_id: props.repositoryId },
                query: { dry_run: false, verbose: true },
            },
        })
        handleResult(data)
        // Don't auto-refresh - let user see results first, they can click "New Preview" to refresh
    } catch (e) {
        notifyOnCatch(e)
    } finally {
        loading.value = false
    }
}

function clearPreview() {
    // If we had completed a non-dry-run reset, refresh parent data
    if (previewResult.value && !previewResult.value.dry_run) {
        emit("resetComplete")
    }
    previewResult.value = null
    viewMode.value = "table"
}
</script>

<template>
    <div>
        <!-- Initial state -->
        <q-banner v-if="!previewResult" class="bg-blue-1 q-mb-md">
            <template #avatar>
                <q-icon name="sym_r_info" color="primary" />
            </template>
            <div><strong>Reset metadata</strong> regenerates all revision metadata from repository contents.</div>
            <div class="q-mt-sm text-caption">
                Use cases:
                <ul class="q-mb-none">
                    <li>Fix corrupted tool_config paths after migration</li>
                    <li>Refresh metadata after tool shed code updates</li>
                    <li>Repair missing or incomplete metadata</li>
                </ul>
            </div>
            <template #action>
                <q-btn color="primary" label="Preview Changes" @click="runPreview" :loading="loading" />
            </template>
        </q-banner>

        <!-- Results -->
        <div v-if="previewResult">
            <q-card class="q-mb-md">
                <q-card-section>
                    <div class="row items-center justify-between">
                        <div>
                            <span class="text-weight-bold">
                                {{ previewResult.dry_run ? "Preview Results" : "Reset Complete" }}
                            </span>
                            <q-chip
                                :color="previewResult.status === 'ok' ? 'positive' : 'warning'"
                                size="sm"
                                class="q-ml-sm"
                            >
                                {{ previewResult.status }}
                            </q-chip>
                            <span v-if="previewResult.dry_run" class="text-caption q-ml-sm">(dry run)</span>
                        </div>
                        <div>
                            <q-btn
                                v-if="previewResult.dry_run"
                                color="primary"
                                label="Apply Now"
                                @click="applyReset"
                                :loading="loading"
                            />
                            <q-btn flat label="New Preview" @click="clearPreview" class="q-ml-sm" :disable="loading" />
                        </div>
                    </div>
                </q-card-section>
            </q-card>

            <!-- View mode toggle -->
            <q-btn-toggle v-model="viewMode" :options="viewModeOptions" class="q-mb-md" />

            <!-- Summary Table View -->
            <ChangesetSummaryTable
                v-if="viewMode === 'table' && previewResult.changeset_details"
                :changesets="previewResult.changeset_details"
            />
            <div v-else-if="viewMode === 'table'" class="text-grey">No changeset details available</div>

            <!-- JSON Diff View -->
            <div v-if="viewMode === 'diff'">
                <JsonDiffViewer
                    v-if="previewResult.repository_metadata_before && previewResult.repository_metadata_after"
                    :before="previewResult.repository_metadata_before"
                    :after="previewResult.repository_metadata_after"
                />
                <div v-else class="text-grey">No diff data available</div>
            </div>

            <!-- Log Messages View -->
            <LogMessagesViewer v-if="viewMode === 'log'" :messages="logMessages" />
        </div>
    </div>
</template>
