<script setup lang="ts">
import { faListUl, faSitemap } from "@fortawesome/free-solid-svg-icons";
import { FontAwesomeIcon } from "@fortawesome/vue-fontawesome";
import { BFormInput } from "bootstrap-vue";
import { computed, ref, watch } from "vue";

import { filterTree, type StepParameterNode, type StepParameterPickerView } from "./stepParameterTree";

import StepParameterTreeNode from "./StepParameterTreeNode.vue";
import StepParameterWorkflowView from "./StepParameterWorkflowView.vue";
import GButton from "@/components/BaseComponents/GButton.vue";
import GModal from "@/components/BaseComponents/GModal.vue";

const props = defineProps<{
    show: boolean;
    tree: StepParameterNode[];
    /** Keys of the step parameters the form shows now. */
    selectedKeys: string[];
    /** The list, or the workflow graph popped out to full screen; both edit the same picked set. */
    view: StepParameterPickerView;
    workflowId: string;
    version: number;
}>();

const emit = defineEmits<{
    (e: "update:show", show: boolean): void;
    (e: "update:view", view: StepParameterPickerView): void;
    /** The full picked set: keys left out are removed from the form. */
    (e: "apply", keys: string[]): void;
}>();

const query = ref("");
const selected = ref(new Set<string>());
const visibleTree = computed(() => filterTree(props.tree, query.value));

watch(
    () => props.show,
    (show) => {
        if (show) {
            selected.value = new Set(props.selectedKeys);
            query.value = "";
        }
    },
    { immediate: true },
);

// Toggled in place: a row reads only its own key, so only that row re-renders.
function toggle(key: string) {
    if (selected.value.has(key)) {
        selected.value.delete(key);
    } else {
        selected.value.add(key);
    }
}

function onOk() {
    emit("apply", [...selected.value]);
    emit("update:show", false);
}
</script>

<template>
    <GModal
        :show="show"
        title="Choose step parameters"
        size="medium"
        :fullscreen="view === 'workflow'"
        confirm
        :ok-text="`Apply (${selected.size})`"
        data-description="step parameter picker"
        @update:show="emit('update:show', $event)"
        @ok="onOk">
        <template v-slot:header>
            <GButton
                v-if="view === 'list'"
                outline
                size="small"
                color="blue"
                data-description="step parameter picker workflow view"
                @click="emit('update:view', 'workflow')">
                <FontAwesomeIcon :icon="faSitemap" fixed-width /> Open workflow view
            </GButton>
            <GButton
                v-else
                outline
                size="small"
                color="blue"
                data-description="step parameter picker list view"
                @click="emit('update:view', 'list')">
                <FontAwesomeIcon :icon="faListUl" fixed-width /> Back to list
            </GButton>
        </template>
        <!-- The dialog keeps its content while closed - build the tree's rows only while it is open. -->
        <template v-if="show">
            <div v-show="view === 'list'" data-description="step parameter list">
                <BFormInput
                    v-model="query"
                    size="sm"
                    class="mb-2"
                    placeholder="Filter by step, tool or parameter"
                    data-description="step parameter filter" />
                <ul class="list-unstyled step-parameter-tree mb-0">
                    <StepParameterTreeNode
                        v-for="node in visibleTree"
                        :key="node.id"
                        :node="node"
                        :selected="selected"
                        @toggle="toggle" />
                </ul>
                <p v-if="!visibleTree.length" class="text-muted mb-0">No step parameters match.</p>
            </div>
            <StepParameterWorkflowView
                v-if="view === 'workflow'"
                :workflow-id="workflowId"
                :version="version"
                :tree="tree"
                :selected="selected"
                @toggle="toggle" />
        </template>
    </GModal>
</template>

<style scoped>
.step-parameter-tree {
    max-height: 60vh;
    overflow-y: auto;
}
</style>
