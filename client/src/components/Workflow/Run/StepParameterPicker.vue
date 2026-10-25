<script setup lang="ts">
import { BFormInput } from "bootstrap-vue";
import { computed, ref, watch } from "vue";

import { filterTree, type StepParameterNode } from "./stepParameterTree";

import StepParameterTreeNode from "./StepParameterTreeNode.vue";
import GModal from "@/components/BaseComponents/GModal.vue";

const props = defineProps<{
    show: boolean;
    tree: StepParameterNode[];
    exposedKeys: string[];
}>();

const emit = defineEmits<{
    (e: "update:show", show: boolean): void;
    (e: "add", keys: string[]): void;
}>();

const query = ref("");
const selected = ref(new Set<string>());
const exposed = computed(() => new Set(props.exposedKeys));
const visibleTree = computed(() => filterTree(props.tree, query.value));

watch(
    () => props.show,
    (show) => {
        if (show) {
            selected.value = new Set();
            query.value = "";
        }
    },
);

function toggle(key: string) {
    const next = new Set(selected.value);
    if (next.has(key)) {
        next.delete(key);
    } else {
        next.add(key);
    }
    selected.value = next;
}

function onOk() {
    emit("add", [...selected.value]);
    emit("update:show", false);
}
</script>

<template>
    <GModal
        :show="show"
        title="Add step parameters"
        size="medium"
        confirm
        :ok-text="`Add (${selected.size})`"
        data-description="step parameter picker"
        @update:show="emit('update:show', $event)"
        @ok="onOk">
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
                :exposed="exposed"
                @toggle="toggle" />
        </ul>
        <p v-if="!visibleTree.length" class="text-muted mb-0">No step parameters match.</p>
    </GModal>
</template>

<style scoped>
.step-parameter-tree {
    max-height: 60vh;
    overflow-y: auto;
}
</style>
