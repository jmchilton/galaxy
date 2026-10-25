<script setup lang="ts">
import { computed } from "vue";

import { hasSelectableLeaf, type StepParameterNode } from "./stepParameterTree";

const props = defineProps<{
    node: StepParameterNode;
    selected: Set<string>;
    exposed: Set<string>;
}>();

const emit = defineEmits<{
    (e: "toggle", key: string): void;
}>();

const muted = computed(() => props.node.kind !== "leaf" && !hasSelectableLeaf(props.node));
</script>

<template>
    <li :class="['step-param-node', `step-param-${node.kind}`, { 'text-muted': muted }]">
        <label
            v-if="node.kind === 'leaf'"
            class="mb-0 d-flex align-items-center"
            :data-exposure-key="node.key"
            :title="node.disabledReason || node.key">
            <input
                type="checkbox"
                class="mr-2"
                :disabled="Boolean(node.disabledReason) || exposed.has(node.key || '')"
                :checked="selected.has(node.key || '') || exposed.has(node.key || '')"
                @change="emit('toggle', node.key || '')" />
            <span>{{ node.label }}</span>
            <code class="ml-2 small text-muted">{{ node.key }}</code>
            <em v-if="node.disabledReason" class="ml-2 small">({{ node.disabledReason }})</em>
            <em v-else-if="exposed.has(node.key || '')" class="ml-2 small">(already added)</em>
        </label>
        <span v-else :class="{ 'font-weight-bold': node.kind === 'step' }">
            {{ node.label }}
            <span v-if="node.badge" class="badge badge-secondary ml-1" title="Fixed - change it in the expanded form">
                = {{ node.badge }}
            </span>
        </span>
        <ul v-if="node.children.length" class="list-unstyled pl-3 mb-1">
            <StepParameterTreeNode
                v-for="child in node.children"
                :key="child.id"
                :node="child"
                :selected="selected"
                :exposed="exposed"
                @toggle="emit('toggle', $event)" />
        </ul>
    </li>
</template>
