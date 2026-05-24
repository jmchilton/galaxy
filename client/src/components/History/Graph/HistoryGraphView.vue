<script setup lang="ts">
import { faClock } from "@fortawesome/free-regular-svg-icons";
import { faBezierCurve, faExchangeAlt } from "@fortawesome/free-solid-svg-icons";
import { FontAwesomeIcon } from "@fortawesome/vue-fontawesome";
import { BAlert, BNav, BNavItem } from "bootstrap-vue";
import { storeToRefs } from "pinia";
import { computed, ref, toRef, watch } from "vue";

import { userOwnsHistory } from "@/api";
import type { GraphNode } from "@/components/Graph/types";
import { useConfig } from "@/composables/config";
import { useExtendedHistory } from "@/composables/detailedHistory";
import { usePersistentToggle } from "@/composables/persistentToggle";
import { addHistoryViewerSubscription, removeHistoryViewerSubscription } from "@/composables/useNotificationSSE";
import { useHistoryStore } from "@/stores/historyStore";
import { useUserStore } from "@/stores/userStore";

import { mapEdges, mapNodes } from "./historyGraphMapper";
import { useHistoryGraphData } from "./useHistoryGraphData";

import HistoryGraphOverview from "./HistoryGraphOverview.vue";
import HistoryGraphReport from "./HistoryGraphReport.vue";
import HistoryGraphToolExecutions from "./HistoryGraphToolExecutions.vue";
import GButton from "@/components/BaseComponents/GButton.vue";
import NavigationTitle from "@/components/Common/NavigationTitle.vue";
import HistoryDatasetsBadge from "@/components/History/HistoryDatasetsBadge.vue";
import LoadingSpan from "@/components/LoadingSpan.vue";
import UtcDate from "@/components/UtcDate.vue";

interface Props {
    historyId: string;
    /** Active tab — undefined means the Overview tab. */
    tab?: string;
    seedSrc?: string;
    seedId?: string;
}

const props = defineProps<Props>();

// History summary — feeds the title and the collapsible info block.
// useExtendedHistory loads the history with size/count details if missing and
// stays reactive when the store updates it (via SSE pushes or polling).
const historyStore = useHistoryStore();
const { currentHistoryId } = storeToRefs(historyStore);
const { currentUser } = storeToRefs(useUserStore());
const { config } = useConfig();
const { history } = useExtendedHistory(props.historyId);
const historyName = computed(() => history.value?.name ?? "...");

// Whether this is the user's current history — drives the Switch to / Current button.
const isCurrent = computed(() => currentHistoryId.value === props.historyId);
async function switchHistory() {
    await historyStore.setCurrentHistory(props.historyId);
}

// Collapsible header info block.
const { toggled: headerCollapsed, toggle: toggleHeaderCollapse } = usePersistentToggle(
    "history-graph-header-collapsed",
);

// Fetch params — product decisions owned here
const limit = ref(500);

const { graphData, loading, error, refetch } = useHistoryGraphData(
    toRef(props, "historyId"),
    limit,
    toRef(props, "seedSrc"),
    toRef(props, "seedId"),
);

// Refresh the graph whenever the underlying history's update_time changes.
// The store keeps that fresh via SSE push (for the current history, owned
// histories, and any history we've subscribed to below) or via the polling
// fallback when SSE is off. Skip the initial transition (undefined → first
// value) since useHistoryGraphData already fires `immediate: true`.
watch(
    () => history.value?.update_time,
    (newT, oldT) => {
        if (newT && oldT && newT !== oldT) {
            refetch();
        }
    },
);

// Mirror the History Multiview pattern: in SSE mode, register a per-history
// viewer subscription so the server pushes events for histories the current
// user doesn't own. Owned histories already get pushes via the general
// channel. In polling mode this is skipped (no SSE channel to push to).
const needsViewerSubscription = computed(() => {
    if (!config.value?.enable_sse_updates) {
        return false;
    }
    if (!history.value || !currentUser.value) {
        return false;
    }
    return !userOwnsHistory(currentUser.value, history.value);
});

watch(
    [needsViewerSubscription, () => props.historyId],
    ([subscribe, id], _previous, onCleanup) => {
        if (!subscribe || !id) {
            return;
        }
        addHistoryViewerSubscription(id);
        onCleanup(() => removeHistoryViewerSubscription(id));
    },
    { immediate: true },
);

// Renderer focus key mirrors the mapper's `${src}:${id}` node key.
const focusNodeId = computed(() => (props.seedSrc && props.seedId ? `${props.seedSrc}:${props.seedId}` : null));

// Graph structure for the renderer — GraphView measures and positions it.
const graphNodes = computed<GraphNode[]>(() =>
    graphData.value ? mapNodes(graphData.value.nodes, graphData.value.edges) : [],
);
const graphEdges = computed(() => (graphData.value ? mapEdges(graphData.value.edges) : []));

const isTruncated = computed(() => graphData.value?.truncated?.item_count_capped ?? false);

// Tab state is internal — driven by clicks, not by URL changes — so switching
// tabs doesn't change `$route.fullPath` and therefore doesn't trip the
// `<router-view :key="$route.fullPath">` remount in Analysis.vue. The URL's
// `:tab?` param is only used as the initial selection (deep-link entry).
type TabKey = "overview" | "tool-requests" | "report";
const activeTab = ref<TabKey>(
    props.tab === "tool-requests" ? "tool-requests" : props.tab === "report" ? "report" : "overview",
);

// AI Summary calls an LLM on mount, so keep it lazy until the user actually
// visits the tab at least once. After that it stays mounted (v-show) so the
// fetched report persists across tab switches.
const reportEverActive = ref(activeTab.value === "report");
watch(activeTab, (val) => {
    if (val === "report") {
        reportEverActive.value = true;
    }
});

// Tool-execution nodes (backend node src is still `tool_request`) feed the Tool Executions tab.
const toolExecutionNodes = computed<GraphNode[]>(() =>
    graphNodes.value.filter((node) => (node.data?.src as string) === "tool_request"),
);
</script>

<template>
    <div class="history-graph-view">
        <BAlert v-if="error" variant="danger" show>{{ error }}</BAlert>
        <LoadingSpan v-else-if="loading" message="Loading history graph" />
        <BAlert v-else-if="graphNodes.length === 0" show variant="info" class="m-3">
            This history is empty. Add datasets or run tools to populate it.
        </BAlert>
        <BAlert v-else-if="toolExecutionNodes.length === 0" show variant="info" class="m-3">
            No History Graph available. Please ensure that the History contains tool executions, and note that
            Galaxy started capturing the required tool execution data with release 26.1.
        </BAlert>
        <template v-else>
            <NavigationTitle
                :icon="faBezierCurve"
                :title="`History Graph: ${historyName}`"
                heading-description="history graph heading"
                collapsible
                :collapsed="headerCollapsed"
                @toggle="toggleHeaderCollapse">
                <template v-slot:actions>
                    <GButton
                        v-if="isCurrent"
                        disabled
                        size="small"
                        color="blue"
                        tooltip
                        title="This history is your current history">
                        Current
                    </GButton>
                    <GButton
                        v-else
                        size="small"
                        color="blue"
                        tooltip
                        title="Set as current history"
                        @click="switchHistory">
                        <FontAwesomeIcon :icon="faExchangeAlt" fixed-width />
                        Set as Current
                    </GButton>
                </template>
                <template v-slot:collapsible>
                    <div
                        v-if="history"
                        class="history-graph-info px-2 py-1 mt-1 text-muted d-flex justify-content-between align-items-center">
                        <i data-description="history graph time info">
                            <FontAwesomeIcon :icon="faClock" class="mr-1" />
                            <span v-localize>updated</span>
                            <UtcDate :date="history.update_time" mode="elapsed" />
                        </i>
                        <HistoryDatasetsBadge :history-id="historyId" :count="history.count" />
                    </div>
                </template>
            </NavigationTitle>

            <BNav pills class="mb-2 mt-2 p-2 bg-light border-bottom">
                <BNavItem
                    title="Overview"
                    :active="activeTab === 'overview'"
                    href="#"
                    @click.prevent="activeTab = 'overview'">
                    Overview
                </BNavItem>
                <BNavItem
                    title="Tool Executions"
                    :active="activeTab === 'tool-requests'"
                    href="#"
                    @click.prevent="activeTab = 'tool-requests'">
                    Tool Executions
                </BNavItem>
                <BNavItem
                    title="AI Summary"
                    :active="activeTab === 'report'"
                    href="#"
                    @click.prevent="activeTab = 'report'">
                    AI Summary
                </BNavItem>
            </BNav>
            <div class="tab-content-container d-flex flex-column overflow-auto">
                <HistoryGraphOverview
                    v-show="activeTab === 'overview'"
                    :nodes="graphNodes"
                    :edges="graphEdges"
                    :focus-node-id="focusNodeId"
                    :truncated="isTruncated" />
                <HistoryGraphToolExecutions
                    v-show="activeTab === 'tool-requests'"
                    :nodes="toolExecutionNodes" />
                <HistoryGraphReport
                    v-if="reportEverActive"
                    v-show="activeTab === 'report'"
                    :history-id="historyId" />
            </div>
        </template>
    </div>
</template>

<style lang="scss" scoped>
.history-graph-view {
    display: flex;
    flex-direction: column;
    height: 100%;
    min-height: 400px;
}

.tab-content-container {
    flex: 1;
    min-height: 0;
}
</style>
