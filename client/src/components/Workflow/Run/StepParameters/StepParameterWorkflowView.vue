<script setup lang="ts">
import { storeToRefs } from "pinia";
import { computed, nextTick, ref, watch } from "vue";

import { fromSimple } from "@/components/Workflow/Editor/modules/model";
import { provideScopedWorkflowStores } from "@/composables/workflowStores";
import { useDatatypesMapperStore } from "@/stores/datatypesMapperStore";
import type { Step } from "@/stores/workflowStepStore";
import { useWorkflowStore } from "@/stores/workflowStore";
import { errorMessageAsString } from "@/utils/simple-error";

import { stepParameterGraphSteps } from "./stepParameterGraph";
import type { StepParameterNode } from "./stepParameterTree";

import StepParameterTreeNode from "./StepParameterTreeNode.vue";
import GAlert from "@/components/BaseComponents/GAlert.vue";
import Heading from "@/components/Common/Heading.vue";
import LoadingSpan from "@/components/LoadingSpan.vue";
import WorkflowGraph from "@/components/Workflow/Editor/WorkflowGraph.vue";

const props = defineProps<{
    workflowId: string;
    version: number;
    /** The picker's tree: its top-level node ids are step indexes, the graph's step ids. */
    tree: StepParameterNode[];
    selected: Set<string>;
}>();

const emit = defineEmits<{
    (e: "toggle", key: string): void;
}>();

// Its own store scope, so clicking a node here doesn't move the run form's active step.
const storeId = `${props.workflowId}-${props.version}-step-parameters`;
const { stateStore, stepStore } = provideScopedWorkflowStores(storeId);
const { activeNodeId } = storeToRefs(stateStore);

const datatypesMapperStore = useDatatypesMapperStore();
const { datatypesMapper } = storeToRefs(datatypesMapperStore);
datatypesMapperStore.createMapper();

const workflowSteps = ref<Record<string, Step> | null>(null);
const errorMessage = ref<string>();
const graph = ref<InstanceType<typeof WorkflowGraph> | null>(null);

async function load() {
    try {
        const workflow = await useWorkflowStore().getFullWorkflowCached(props.workflowId, props.version);
        // The scope outlives this view by a moment: reopening it right away finds the steps loaded.
        if (!Object.keys(stepStore.steps).length) {
            await fromSimple(storeId, workflow);
        }
        activeNodeId.value = null;
        workflowSteps.value = workflow.steps;
    } catch (e) {
        errorMessage.value = errorMessageAsString(e);
    }
}

load();

watch(graph, async (graphComponent) => {
    if (graphComponent) {
        await nextTick();
        graphComponent.fitWorkflow(0.25, 1.0, 20.0);
    }
});

const steps = computed(() =>
    workflowSteps.value ? stepParameterGraphSteps(workflowSteps.value, props.tree, props.selected) : null,
);

const activeNode = computed(() => props.tree.find((node) => node.id === String(activeNodeId.value)));
const activeTitle = computed(() => {
    if (activeNode.value) {
        return activeNode.value.label;
    }
    const step = activeNodeId.value === null ? undefined : workflowSteps.value?.[activeNodeId.value];
    return step ? `Step ${step.id + 1}: ${step.label || step.name}` : "";
});
</script>

<template>
    <GAlert v-if="errorMessage" variant="danger" show>{{ errorMessage }}</GAlert>
    <LoadingSpan v-else-if="!steps || !datatypesMapper" message="Loading workflow" />
    <div v-else class="d-flex step-parameter-workflow-view" data-description="step parameter workflow view">
        <div class="flex-grow-1 border rounded mr-2 step-parameter-workflow-graph">
            <WorkflowGraph
                ref="graph"
                :steps="steps"
                :datatypes-mapper="datatypesMapper"
                :show-minimap="false"
                is-invocation
                readonly />
        </div>
        <div class="step-parameter-workflow-panel" data-description="step parameter workflow panel">
            <span class="sr-only" aria-live="polite">{{ activeTitle }}</span>
            <!-- The graph's nodes can't be reached by keyboard; this picks the same step. -->
            <label class="d-block small mb-2">
                Step
                <select
                    v-model="activeNodeId"
                    class="custom-select custom-select-sm"
                    data-description="step parameter workflow step select">
                    <option :value="null" disabled>Choose a step</option>
                    <option v-for="node in tree" :key="node.id" :value="Number(node.id)">{{ node.label }}</option>
                </select>
            </label>
            <p v-if="activeNodeId === null" class="text-muted">
                Click a tool or subworkflow step, or choose one above, to pick which of its parameters to set for this
                run.
            </p>
            <template v-else>
                <Heading h3 size="sm" bold>{{ activeTitle }}</Heading>
                <template v-if="activeNode?.children.length">
                    <p v-if="activeNode.kind === 'subworkflow'" class="small text-muted mb-2">
                        Parameters of the tool steps inside this subworkflow.
                    </p>
                    <ul class="list-unstyled mb-0">
                        <StepParameterTreeNode
                            v-for="child in activeNode.children"
                            :key="child.id"
                            :node="child"
                            :selected="selected"
                            @toggle="emit('toggle', $event)" />
                    </ul>
                </template>
                <p v-else class="text-muted">
                    This step has no parameters to choose. Workflow inputs are set in the run form.
                </p>
            </template>
        </div>
    </div>
</template>

<style scoped>
.step-parameter-workflow-view {
    height: 70vh;
}
.step-parameter-workflow-graph {
    min-width: 0;
    position: relative;
}
.step-parameter-workflow-panel {
    width: 24rem;
    flex-shrink: 0;
    overflow-y: auto;
}
</style>
