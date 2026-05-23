<script setup lang="ts">
import { faClock } from "@fortawesome/free-regular-svg-icons";
import { faBezierCurve, faExchangeAlt } from "@fortawesome/free-solid-svg-icons";
import { FontAwesomeIcon } from "@fortawesome/vue-fontawesome";
import { BAlert, BNav, BNavItem } from "bootstrap-vue";
import { storeToRefs } from "pinia";
import { computed, ref, toRef } from "vue";

import type { GraphNode } from "@/components/Graph/types";
import { usePersistentToggle } from "@/composables/persistentToggle";
import { useHistoryStore } from "@/stores/historyStore";

import { mapEdges, mapNodes } from "./historyGraphMapper";
import { useHistoryGraphData } from "./useHistoryGraphData";

import HistoryGraphOverview from "./HistoryGraphOverview.vue";
import HistoryGraphReport from "./HistoryGraphReport.vue";
import HistoryGraphToolRequests from "./HistoryGraphToolRequests.vue";
import GButton from "@/components/BaseComponents/GButton.vue";
import NavigationTitle from "@/components/Common/NavigationTitle.vue";
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
const historyStore = useHistoryStore();
const { currentHistoryId } = storeToRefs(historyStore);
const history = computed(() => historyStore.getHistoryById(props.historyId));
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

const { graphData, loading, error } = useHistoryGraphData(
    toRef(props, "historyId"),
    limit,
    toRef(props, "seedSrc"),
    toRef(props, "seedId"),
);

// Renderer focus key mirrors the mapper's `${src}:${id}` node key.
const focusNodeId = computed(() => (props.seedSrc && props.seedId ? `${props.seedSrc}:${props.seedId}` : null));

// Graph structure for the renderer — GraphView measures and positions it.
const graphNodes = computed<GraphNode[]>(() =>
    graphData.value ? mapNodes(graphData.value.nodes, graphData.value.edges) : [],
);
const graphEdges = computed(() => (graphData.value ? mapEdges(graphData.value.edges) : []));

const isTruncated = computed(() => graphData.value?.truncated?.item_count_capped ?? false);

// `tab` undefined means the Overview tab.
const onOverviewTab = computed(() => !props.tab);

// Tool request nodes feed the "Tool Executions" tab.
const toolRequestNodes = computed<GraphNode[]>(() =>
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
        <BAlert v-else-if="toolRequestNodes.length === 0" show variant="info" class="m-3">
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
                    <div v-if="history" class="history-graph-info px-2 py-1 small text-muted">
                        <i data-description="history graph time info">
                            <FontAwesomeIcon :icon="faClock" class="mr-1" />
                            <span v-localize>updated</span>
                            <UtcDate :date="history.update_time" mode="elapsed" />
                        </i>
                        <span class="ml-3">{{ history.count }} items</span>
                    </div>
                </template>
            </NavigationTitle>

            <BNav pills class="mb-2 mt-2 p-2 bg-light border-bottom">
                <BNavItem title="Overview" :active="onOverviewTab" :to="`/histories/${historyId}/graph`">
                    Overview
                </BNavItem>
                <BNavItem
                    title="Tool Executions"
                    :active="props.tab === 'tool-requests'"
                    :to="`/histories/${historyId}/graph/tool-requests`">
                    Tool Executions
                </BNavItem>
                <BNavItem
                    title="AI Summary"
                    :active="props.tab === 'report'"
                    :to="`/histories/${historyId}/graph/report`">
                    AI Summary
                </BNavItem>
            </BNav>
            <div class="tab-content-container d-flex flex-column overflow-auto">
                <HistoryGraphOverview
                    v-if="onOverviewTab"
                    :nodes="graphNodes"
                    :edges="graphEdges"
                    :focus-node-id="focusNodeId"
                    :truncated="isTruncated" />
                <HistoryGraphToolRequests v-else-if="props.tab === 'tool-requests'" :nodes="toolRequestNodes" />
                <HistoryGraphReport v-else-if="props.tab === 'report'" :history-id="historyId" />
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
