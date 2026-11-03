<script setup lang="ts">
import { BFormInput } from "bootstrap-vue";
import { computed, ref, watch } from "vue";

import { filterTree, type StepParameterNode } from "./stepParameterTree";

import StepParameterTreeNode from "./StepParameterTreeNode.vue";
import GModal from "@/components/BaseComponents/GModal.vue";

const props = defineProps<{
    show: boolean;
    tree: StepParameterNode[];
    /** Keys of the step parameters the form shows now. */
    selectedKeys: string[];
}>();

const emit = defineEmits<{
    (e: "update:show", show: boolean): void;
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
        confirm
        :ok-text="`Apply (${selected.size})`"
        data-description="step parameter picker"
        @update:show="emit('update:show', $event)"
        @ok="onOk">
        <!-- The dialog keeps its content while closed - build the tree's rows only while it is open. -->
        <template v-if="show">
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
        </template>
    </GModal>
</template>

<style scoped>
.step-parameter-tree {
    max-height: 60vh;
    overflow-y: auto;
}
</style>
