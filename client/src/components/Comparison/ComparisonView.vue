<script setup lang="ts">
import { faTimes } from "@fortawesome/free-solid-svg-icons";
import { FontAwesomeIcon } from "@fortawesome/vue-fontawesome";
import { computed, ref, watch } from "vue";
import { type LocationQuery, useRouter } from "vue-router";

import {
    type ComparisonRequest,
    type ComparisonTable as ComparisonTableModel,
    fetchComparison,
} from "@/api/comparisons";
import { getWorkflowInfo } from "@/api/workflows";
import type { BreadcrumbItem } from "@/components/Common";
import { useToolStore } from "@/stores/toolStore";

import {
    cleanUrlQuery,
    type ComparisonUrlValue,
    DEFAULT_LIMIT,
    type DisplayKeyQuery,
    displayStorageKey,
    PAGE_SIZES,
    parseComparisonQuery,
} from "./comparisonQuery";
import { requestedMetadata } from "./comparisonUtils";
import { useComparisonDisplay, useComparisonFetch } from "./useComparison";

import ComparisonFilters from "./ComparisonFilters.vue";
import ComparisonPager from "./ComparisonPager.vue";
import ComparisonTable from "./ComparisonTable.vue";
import GAlert from "@/components/BaseComponents/GAlert.vue";
import GButton from "@/components/BaseComponents/GButton.vue";
import GCheckbox from "@/components/BaseComponents/GCheckbox.vue";
import GCheckboxGroup from "@/components/BaseComponents/GCheckboxGroup.vue";
import GSelect from "@/components/BaseComponents/GSelect.vue";
import BreadcrumbHeading from "@/components/Common/BreadcrumbHeading.vue";
import LoadingSpan from "@/components/LoadingSpan.vue";

const props = defineProps<{
    /** The route's query: `kind` plus the matching endpoint's parameters. */
    query: LocationQuery;
}>();

const router = useRouter();
const toolStore = useToolStore();

const parsed = computed(() => parseComparisonQuery(props.query));
const request = computed(() => (parsed.value.kind ? (parsed.value as ComparisonRequest) : undefined));
const kind = computed(() => request.value?.kind);
const urlParams = computed(() => (request.value?.params ?? {}) as Record<string, ComparisonUrlValue>);

const table = ref<ComparisonTableModel>();
// With `instance` the URL names a workflow version, so wait for the echoed stored workflow id.
const storageKey = computed(() => {
    if (request.value && urlParams.value.instance !== true) {
        return displayStorageKey({ kind: request.value.kind, ...request.value.params } as DisplayKeyQuery);
    }
    return table.value ? displayStorageKey(table.value.query) : undefined;
});
const { transpose, columnDisplay, visibleColumns, toggleColumn, resetColumns } = useComparisonDisplay(
    storageKey,
    table,
);

// The URL's parameters as they are, plus the metadata the column displays need.
const fetchRequest = computed<ComparisonRequest | undefined>(() => {
    if (!request.value) {
        return undefined;
    }
    const fromUrl = (request.value.params.metadata_elements as string[] | undefined) ?? [];
    const metadata = [...new Set([...fromUrl, ...requestedMetadata(columnDisplay.value)])].sort();
    return {
        ...request.value,
        params: { ...request.value.params, metadata_elements: metadata.length ? metadata : undefined },
    } as ComparisonRequest;
});
const { total, loading, error, reload } = useComparisonFetch(fetchRequest, fetchComparison, table);

// The page stays mounted across URL changes; drop the old table once the URL names another comparison.
const identity = computed(() => {
    const params = urlParams.value;
    return JSON.stringify([kind.value, params.workflow_id, params.instance, params.step_label, params.tool_id]);
});
watch(identity, () => {
    table.value = undefined;
});

const limit = computed(() => Number(urlParams.value.limit) || DEFAULT_LIMIT);
const offset = computed(() => Number(urlParams.value.offset) || 0);

function listParam(key: string): string[] {
    const value = urlParams.value[key];
    return Array.isArray(value) ? value.filter((item): item is string => item !== null) : [];
}

/** Writes filters or paging to the URL; any change but paging returns to the first page. */
function updateUrl(patch: Record<string, ComparisonUrlValue>) {
    const next: Record<string, ComparisonUrlValue> = { ...props.query, ...patch };
    if (!("offset" in patch) || !patch.offset) {
        delete next.offset;
    }
    router.replace({ query: cleanUrlQuery(next) });
}

const states = computed({
    get: () => listParam("states"),
    set: (value: string[]) => updateUrl({ states: value }),
});
const versions = computed({
    get: () => (kind.value === "step_runs" ? listParam("versions") : undefined),
    set: (value: string[] | undefined) => updateUrl({ versions: value }),
});

const toolVersions = computed({
    get: () => listParam("tool_versions"),
    set: (value: string[]) => updateUrl({ tool_versions: value }),
});
const toolVersionOptions = computed(() =>
    [...new Set([...(table.value?.tool_versions_available ?? []), ...toolVersions.value])].map((version) => ({
        text: version,
        value: version,
    })),
);

const includeWorkflowJobs = computed({
    get: () => urlParams.value.include_workflow_jobs !== false,
    set: (value: boolean) => updateUrl({ include_workflow_jobs: value ? undefined : false }),
});

const historyFilterName = computed(() => {
    const historyId = urlParams.value.history_id;
    return table.value?.rows.find((row) => row.history.id === historyId)?.history.name || historyId;
});

const outputLabels = computed({
    get: () => listParam("output_labels"),
    set: (value: string[]) => updateUrl({ output_labels: value }),
});
const outputLabelOptions = computed(() =>
    [...new Set([...(table.value?.output_labels_available ?? []), ...outputLabels.value])].map((label) => ({
        text: label,
        value: label,
    })),
);

const pageSize = computed({
    get: () => limit.value,
    set: (value: number) => updateUrl({ limit: value === DEFAULT_LIMIT ? undefined : value }),
});
const pageSizeOptions = computed(() =>
    [...new Set([...PAGE_SIZES, limit.value])].sort((a, b) => a - b).map((size) => ({ text: `${size}`, value: size })),
);

const workflowName = ref<string>();
watch(
    () => (kind.value === "tool_runs" ? undefined : urlParams.value.workflow_id),
    async (workflowId) => {
        workflowName.value = undefined;
        if (!workflowId) {
            return;
        }
        try {
            const workflow = await getWorkflowInfo(String(workflowId), undefined, urlParams.value.instance === true);
            workflowName.value = workflow.name;
        } catch {
            // The heading falls back to a generic name; the table shows any access error.
        }
    },
    { immediate: true },
);

const toolId = computed(() => (kind.value === "tool_runs" ? String(urlParams.value.tool_id) : undefined));
watch(
    toolId,
    async (id) => {
        if (id && !toolStore.getToolForId(id)) {
            try {
                await toolStore.fetchToolForId(id);
            } catch {
                // An uninstalled tool still has runs; the heading shows its id.
            }
        }
    },
    { immediate: true },
);

const breadcrumbs = computed<BreadcrumbItem[]>(() => {
    if (kind.value === "tool_runs") {
        return [{ title: `Runs of ${toolStore.getToolNameById(toolId.value!, toolId.value)}` }];
    }
    // The echoed id is the stored workflow's even when the URL named a version with `instance`.
    const storedId = table.value && "workflow_id" in table.value.query ? table.value.query.workflow_id : undefined;
    const workflow = {
        title: workflowName.value ?? "Workflow",
        to: storedId ? `/workflows/${storedId}/invocations` : undefined,
    };
    const last = kind.value === "step_runs" ? `Runs of step "${urlParams.value.step_label}"` : "Compare outputs";
    return [{ title: "Workflows", to: "/workflows/list" }, workflow, { title: last }];
});
</script>

<template>
    <div class="comparison-view">
        <GAlert v-if="!request" variant="danger" show>{{ "error" in parsed ? parsed.error : "" }}</GAlert>
        <template v-else>
            <BreadcrumbHeading :items="breadcrumbs" />
            <p class="comparison-view-description text-muted mb-2">
                <template v-if="kind === 'step_runs'">
                    Every run of the step labelled <code>{{ urlParams.step_label }}</code
                    >, across the versions of this workflow that have it.
                </template>
                <template v-else-if="kind === 'output_runs'">
                    Labelled inputs and outputs of every run of this workflow, merged across versions. Columns only
                    older versions have go last.
                </template>
                <template v-else>
                    Every submission of <code>{{ toolId }}</code
                    >, across tool versions. A mapped-over batch is one row.
                </template>
            </p>

            <ComparisonFilters
                v-model:states="states"
                v-model:versions="versions"
                :kind="kind!"
                :versions-available="table?.versions_available">
                <GCheckboxGroup
                    v-if="kind === 'output_runs' && outputLabelOptions.length"
                    v-model="outputLabels"
                    class="comparison-filter-outputs mr-4"
                    label="Outputs (none checked shows all)"
                    :options="outputLabelOptions"
                    size="small" />
                <template v-if="kind === 'tool_runs'">
                    <GCheckboxGroup
                        v-if="toolVersionOptions.length"
                        v-model="toolVersions"
                        class="comparison-filter-tool-versions mr-4"
                        label="Tool version"
                        :options="toolVersionOptions"
                        size="small" />
                    <div class="mr-4">
                        <GCheckbox v-model="includeWorkflowJobs" class="comparison-filter-workflow-jobs" switch>
                            Include runs inside workflows
                        </GCheckbox>
                        <GButton
                            v-if="urlParams.history_id"
                            class="comparison-filter-history mt-1"
                            size="small"
                            outline
                            title="Show runs from every history"
                            @click="updateUrl({ history_id: undefined })">
                            History: {{ historyFilterName }}
                            <FontAwesomeIcon :icon="faTimes" />
                        </GButton>
                    </div>
                </template>
            </ComparisonFilters>

            <GAlert v-if="error" variant="danger" show>
                {{ error }}
                <GButton class="comparison-retry ml-2" size="small" outline @click="reload">Retry</GButton>
            </GAlert>
            <LoadingSpan v-if="loading && !table" message="Loading runs" />
            <template v-if="table">
                <ComparisonTable
                    v-model:transpose="transpose"
                    v-model:column-display="columnDisplay"
                    :table="table"
                    :visible-columns="visibleColumns"
                    :loading="loading"
                    empty-message="No runs match these filters."
                    @toggle-column="toggleColumn"
                    @reset-columns="resetColumns" />
                <ComparisonPager
                    :total="total"
                    :limit="limit"
                    :offset="offset"
                    :loaded-offset="table.query.offset"
                    :sort-by="table.query.sort_by"
                    :sort-desc="table.query.sort_desc"
                    :row-count="table.rows.length"
                    @update:offset="updateUrl({ offset: $event })">
                    <label class="mb-0 mr-1 text-nowrap" for="comparison-page-size"><small>Per page</small></label>
                    <GSelect
                        id="comparison-page-size"
                        v-model="pageSize"
                        class="comparison-page-size"
                        :options="pageSizeOptions"
                        size="small" />
                </ComparisonPager>
            </template>
        </template>
    </div>
</template>
