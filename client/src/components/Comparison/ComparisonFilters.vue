<script setup lang="ts">
import { computed } from "vue";

import type { ComparisonKind } from "@/api/comparisons";

import { STATE_OPTIONS } from "./comparisonQuery";
import { stateText, versionLabel } from "./comparisonUtils";

import GCheckboxGroup from "@/components/BaseComponents/GCheckboxGroup.vue";

const props = withDefaults(
    defineProps<{
        kind: ComparisonKind;
        states: string[];
        /** Selected 0-based workflow versions, as URL strings; undefined when the comparison has no version filter. */
        versions?: string[];
        versionsAvailable?: number[] | null;
    }>(),
    { versions: undefined, versionsAvailable: undefined },
);

const emit = defineEmits<{
    (e: "update:states", value: string[]): void;
    (e: "update:versions", value: string[]): void;
}>();

// Selected values stay offered even when the loaded page doesn't report them.
const stateOptions = computed(() =>
    [...new Set([...STATE_OPTIONS[props.kind], ...props.states])].map((state) => ({
        text: stateText(state),
        value: state,
    })),
);

const versionOptions = computed(() =>
    [...new Set([...(props.versionsAvailable ?? []).map(String), ...(props.versions ?? [])])]
        .sort((a, b) => Number(a) - Number(b))
        .map((version) => ({ text: versionLabel(Number(version)) || version, value: version })),
);
// One version has nothing to choose between.
const showVersions = computed(
    () => props.versions !== undefined && (versionOptions.value.length > 1 || props.versions.length > 0),
);
</script>

<template>
    <div class="comparison-filters d-flex flex-wrap align-items-start mb-2">
        <GCheckboxGroup
            :model-value="states"
            class="comparison-filter-states mr-4"
            label="State"
            :options="stateOptions"
            size="small"
            @update:model-value="emit('update:states', $event)" />
        <GCheckboxGroup
            v-if="showVersions"
            :model-value="versions"
            class="comparison-filter-versions mr-4"
            label="Workflow version"
            :options="versionOptions"
            size="small"
            @update:model-value="emit('update:versions', $event)" />
        <slot />
    </div>
</template>
