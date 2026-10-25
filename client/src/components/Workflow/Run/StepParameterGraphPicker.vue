<script setup lang="ts">
import { faCheckCircle, faLock } from "@fortawesome/free-solid-svg-icons";
import { FontAwesomeIcon } from "@fortawesome/vue-fontawesome";
import { storeToRefs } from "pinia";
import { computed, ref, watch } from "vue";

import { fromSimple } from "@/components/Workflow/Editor/modules/model";
import { getWorkflowFull } from "@/components/Workflow/workflows.services";
import { getHeaderClass } from "@/composables/useInvocationGraph";
import { provideScopedWorkflowStores } from "@/composables/workflowStores";
import { useDatatypesMapperStore } from "@/stores/datatypesMapperStore";
import { errorMessageAsString } from "@/utils/simple-error";

import { type DroppedExposure, hasSelectableLeaf, type StepParameterNode, treeLeaves } from "./stepParameterTree";

import StepParameterTreeNode from "./StepParameterTreeNode.vue";
import GAlert from "@/components/BaseComponents/GAlert.vue";
import GModal from "@/components/BaseComponents/GModal.vue";
import LoadingSpan from "@/components/LoadingSpan.vue";
import WorkflowGraph from "@/components/Workflow/Editor/WorkflowGraph.vue";

const props = defineProps<{
    show: boolean;
    workflowId: string;
    version: number;
    tree: StepParameterNode[];
    exposedKeys: string[];
    /** Subworkflow keys a link or rerun asked for; this picker can't show them. */
    lockedDropped: DroppedExposure[];
}>();

const emit = defineEmits<{
    (e: "update:show", show: boolean): void;
    (e: "apply", keys: string[]): void;
}>();

// Own store scope so picking doesn't move the run form's active step.
const storeId = `${props.workflowId}-step-parameter-picker`;
const { stateStore } = provideScopedWorkflowStores(storeId);
const { activeNodeId } = storeToRefs(stateStore);
const datatypesMapperStore = useDatatypesMapperStore();
const { datatypesMapper } = storeToRefs(datatypesMapperStore);
datatypesMapperStore.createMapper();

const workflow = ref<any>(null);
const errorMessage = ref<string | null>(null);
const picked = ref(new Set<string>());
const none = new Set<string>();

async function load() {
    try {
        const full = await getWorkflowFull(props.workflowId, props.version);
        await fromSimple(storeId, { ...full, id: storeId });
        workflow.value = full;
    } catch (e) {
        errorMessage.value = errorMessageAsString(e);
    }
}

watch(
    () => props.show,
    (show) => {
        if (show) {
            picked.value = new Set(props.exposedKeys);
            activeNodeId.value = null;
            if (!workflow.value) {
                load();
            }
        }
    },
    { immediate: true },
);

const treeByIndex = computed(() => new Map(props.tree.map((node) => [node.id, node])));
const activeNode = computed(() =>
    activeNodeId.value === null ? undefined : treeByIndex.value.get(String(activeNodeId.value)),
);
const activeStepTitle = computed(() => {
    const step = activeNodeId.value === null ? undefined : workflow.value?.steps[activeNodeId.value];
    return step ? `Step ${step.id + 1}: ${step.label || step.name}` : "";
});

function pickedCount(node: StepParameterNode): number {
    return treeLeaves([node]).filter((leaf) => picked.value.has(leaf.key as string)).length;
}

const steps = computed(() => {
    const result: Record<string, any> = {};
    for (const [id, step] of Object.entries<any>(workflow.value?.steps || {})) {
        const node = treeByIndex.value.get(String(step.id));
        if (node?.lockedReason) {
            result[id] = {
                ...step,
                nodeText: "Parameters inside subworkflows can't be picked here",
                headerClass: getHeaderClass("setting_metadata"),
                headerIcon: faLock,
            };
        } else if (node && hasSelectableLeaf(node)) {
            const count = pickedCount(node);
            const total = treeLeaves([node]).filter((leaf) => !leaf.disabledReason).length;
            result[id] = {
                ...step,
                nodeText: count ? `<b>${count}</b> of ${total} parameters picked` : `${total} parameters to pick`,
                headerClass: getHeaderClass(count ? "ok" : undefined),
                headerIcon: count ? faCheckCircle : undefined,
            };
        } else {
            result[id] = { ...step, nodeText: node ? "No parameters to pick" : "Set in the run form" };
        }
    }
    return result;
});

function toggle(key: string) {
    const next = new Set(picked.value);
    if (next.has(key)) {
        next.delete(key);
    } else {
        next.add(key);
    }
    picked.value = next;
}

const okText = computed(() => {
    const dropping = props.lockedDropped.length;
    return dropping
        ? `Apply (${picked.value.size}) - ${dropping} subworkflow parameter(s) not sent`
        : `Apply (${picked.value.size})`;
});

function onOk() {
    emit("apply", [...picked.value]);
    emit("update:show", false);
}
</script>

<template>
    <GModal
        :show="show"
        title="Pick step parameters from the workflow graph"
        size="large"
        confirm
        :ok-text="okText"
        data-description="step parameter graph picker"
        @update:show="emit('update:show', $event)"
        @ok="onOk">
        <GAlert
            v-if="lockedDropped.length"
            variant="danger"
            show
            class="mb-2"
            data-description="graph picker locked subworkflow parameters">
            <FontAwesomeIcon :icon="faLock" fixed-width />
            {{ lockedDropped.length }} requested parameter(s) are inside subworkflows. The graph can't show them, so
            they <b>will not be sent</b> with this run:
            <code v-for="dropped in lockedDropped" :key="dropped.key" class="ml-1">{{ dropped.key }}</code>
        </GAlert>
        <GAlert v-if="errorMessage" variant="danger" show>{{ errorMessage }}</GAlert>
        <LoadingSpan v-else-if="!workflow || !datatypesMapper" message="Loading workflow" />
        <div v-else class="d-flex step-parameter-graph-picker">
            <div class="flex-grow-1 border rounded mr-2 step-parameter-graph">
                <WorkflowGraph
                    :steps="steps"
                    :datatypes-mapper="datatypesMapper"
                    :fixed-height="55"
                    :show-minimap="false"
                    annotated
                    readonly />
            </div>
            <div class="step-parameter-graph-panel" data-description="graph picker step panel">
                <p v-if="activeNodeId === null" class="text-muted">
                    Click a tool step in the graph to pick which of its parameters to set for this run.
                </p>
                <template v-else-if="activeNode?.lockedReason">
                    <h5>{{ activeStepTitle }}</h5>
                    <GAlert variant="warning" show data-description="graph picker subworkflow locked">
                        <FontAwesomeIcon :icon="faLock" fixed-width />
                        {{ activeNode.lockedReason }}. Values passed into this subworkflow from a link or a rerun are
                        dropped. Use the expanded form to change them.
                    </GAlert>
                </template>
                <template v-else-if="activeNode">
                    <h5>{{ activeStepTitle }}</h5>
                    <ul class="list-unstyled mb-0">
                        <StepParameterTreeNode
                            v-for="child in activeNode.children"
                            :key="child.id"
                            :node="child"
                            :selected="picked"
                            :exposed="none"
                            @toggle="toggle" />
                    </ul>
                </template>
                <template v-else>
                    <h5>{{ activeStepTitle }}</h5>
                    <p class="text-muted">This step has no tool parameters. Set workflow inputs in the run form.</p>
                </template>
            </div>
        </div>
    </GModal>
</template>

<style scoped>
.step-parameter-graph {
    min-width: 0;
}
.step-parameter-graph-panel {
    width: 22rem;
    flex-shrink: 0;
    max-height: 55vh;
    overflow-y: auto;
}
</style>
