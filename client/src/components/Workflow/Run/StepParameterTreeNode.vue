<script setup lang="ts">
import { faLock, faQuestionCircle } from "@fortawesome/free-solid-svg-icons";
import { FontAwesomeIcon } from "@fortawesome/vue-fontawesome";
import { computed, ref } from "vue";

import { hasSelectableLeaf, type StepParameterNode } from "./stepParameterTree";

import GPopover from "@/components/BaseComponents/GPopover.vue";
import GTooltip from "@/components/BaseComponents/GTooltip.vue";

const props = defineProps<{
    node: StepParameterNode;
    selected: Set<string>;
    exposed: Set<string>;
}>();

const emit = defineEmits<{
    (e: "toggle", key: string): void;
}>();

const lockRef = ref<HTMLElement | null>(null);
const helpRef = ref<HTMLElement | null>(null);

const isLeaf = computed(() => props.node.kind === "leaf");
const hasRow = computed(() => isLeaf.value || props.node.kind === "conditional");
const muted = computed(() => !hasRow.value && !hasSelectableLeaf(props.node));
const key = computed(() => props.node.key || "");
const isExposed = computed(() => props.exposed.has(key.value));
const valueText = computed(() =>
    props.node.value === undefined ? "workflow leaves this empty" : `workflow sets to ${props.node.value}`,
);
</script>

<template>
    <li :class="['step-param-node', `step-param-${node.kind}`, { 'text-muted': muted }]">
        <div
            v-if="hasRow"
            :class="['step-param-row d-flex align-items-center', { 'step-param-locked': node.disabledReason }]">
            <span
                v-if="node.disabledReason"
                ref="lockRef"
                class="step-param-lock mr-2"
                tabindex="0"
                data-description="step parameter locked">
                <FontAwesomeIcon :icon="faLock" fixed-width />
                <GTooltip :reference="lockRef" :text="node.disabledReason" />
            </span>
            <label
                v-if="isLeaf && !node.disabledReason"
                class="mb-0 d-flex align-items-center"
                :data-exposure-key="node.key">
                <input
                    type="checkbox"
                    class="mr-2"
                    :disabled="isExposed"
                    :checked="selected.has(key) || isExposed"
                    @change="emit('toggle', key)" />
                <span>{{ node.label }}</span>
            </label>
            <span v-else :data-exposure-key="node.key">{{ node.label }}</span>
            <button
                v-if="node.help"
                ref="helpRef"
                type="button"
                class="btn btn-link btn-sm p-0 ml-1 step-param-help"
                data-description="step parameter help"
                :aria-label="`Help for ${node.label}`">
                <FontAwesomeIcon :icon="faQuestionCircle" />
            </button>
            <GPopover v-if="node.help" :target="() => helpRef" triggers="hover focus" :content="node.help" />
            <span class="step-param-value ml-2 small text-muted text-truncate" :title="valueText">
                {{ valueText }}
            </span>
            <em v-if="isLeaf && isExposed" class="ml-2 small text-nowrap">(already added)</em>
        </div>
        <span v-else :class="{ 'font-weight-bold': node.kind === 'step' }">{{ node.label }}</span>
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

<style scoped>
.step-param-row,
.step-param-value {
    min-width: 0;
}
.step-param-locked {
    opacity: 0.6;
}
</style>
