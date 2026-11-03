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
}>();

const emit = defineEmits<{
    (e: "toggle", key: string): void;
}>();

const lockRef = ref<HTMLElement | null>(null);
const helpRef = ref<HTMLElement | null>(null);

/** The parameter or conditional test parameter this node shows as a row, if it isn't a group. */
const row = computed(() => (props.node.kind === "leaf" || props.node.kind === "conditional" ? props.node : undefined));
const muted = computed(() => !row.value && !hasSelectableLeaf(props.node));
const bold = computed(() => props.node.kind === "step" || props.node.kind === "subworkflow");
const valueText = computed(() =>
    row.value?.value === undefined ? "workflow leaves this empty" : `workflow sets to ${row.value.value}`,
);
</script>

<template>
    <li :class="['step-param-node', `step-param-${node.kind}`, { 'text-muted': muted }]">
        <div
            v-if="row"
            :class="['step-param-row d-flex align-items-center', { 'step-param-locked': row.disabledReason }]"
            data-description="step parameter row"
            :data-parameter-key="row.id">
            <!-- Focusable, so the tooltip saying why it is locked (its aria-describedby) shows on keyboard focus too. -->
            <span
                v-if="row.disabledReason"
                ref="lockRef"
                class="step-param-lock d-flex align-items-center"
                tabindex="0"
                data-description="step parameter locked">
                <FontAwesomeIcon :icon="faLock" fixed-width class="mr-2" />
                <span class="sr-only">Locked:</span>
                <span>{{ row.label }}</span>
                <GTooltip
                    :reference="lockRef"
                    :text="row.disabledReason"
                    data-description="step parameter lock tooltip" />
            </span>
            <label v-else-if="row.kind === 'leaf'" class="mb-0 d-flex align-items-center">
                <input type="checkbox" class="mr-2" :checked="selected.has(row.id)" @change="emit('toggle', row.id)" />
                <span>{{ row.label }}</span>
            </label>
            <button
                v-if="row.help"
                ref="helpRef"
                type="button"
                class="btn btn-link btn-sm p-0 ml-1 step-param-help"
                data-description="step parameter help"
                :aria-label="`Help for ${row.label}`">
                <FontAwesomeIcon :icon="faQuestionCircle" />
            </button>
            <GPopover v-if="row.help" :target="() => helpRef" triggers="hover focus">
                <!-- The popover moves to the dialog, so it carries its parameter's key itself. -->
                <span data-description="step parameter help text" :data-parameter-key="row.id">
                    {{ row.help }}
                </span>
            </GPopover>
            <span class="step-param-value ml-2 small text-muted text-truncate" :title="valueText">
                {{ valueText }}
            </span>
        </div>
        <span v-else :class="{ 'font-weight-bold': bold }">{{ node.label }}</span>
        <ul v-if="node.children.length" class="list-unstyled pl-3 mb-1">
            <StepParameterTreeNode
                v-for="child in node.children"
                :key="child.id"
                :node="child"
                :selected="selected"
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
.step-param-lock {
    cursor: help;
}
</style>
