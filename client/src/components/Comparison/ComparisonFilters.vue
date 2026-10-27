<script setup lang="ts">
import { computed } from "vue";

import type { ComparisonKind } from "@/api/comparisons";

import { STATE_OPTIONS } from "./comparisonQuery";
import { offeredOptions, stateFilterOptions, versionLabel } from "./comparisonUtils";

import GCheckboxGroup from "@/components/BaseComponents/GCheckboxGroup.vue";
import GDropdown from "@/components/BaseComponents/GDropdown.vue";
import GDropdownForm from "@/components/BaseComponents/GDropdownForm.vue";

/** Selected state names shown on the closed state menu before it reads "N selected". */
const MAX_NAMED_STATES = 2;

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
const stateOptions = computed(() => stateFilterOptions(STATE_OPTIONS[props.kind], props.states));
const checkedStateOptions = computed(() =>
    stateOptions.value.filter((option) => option.states.some((state) => props.states.includes(state))),
);
const checkedStates = computed(() => checkedStateOptions.value.map((option) => option.value));
const statesSummary = computed(() => {
    const texts = checkedStateOptions.value.map((option) => option.text);
    if (!texts.length) {
        return "any";
    }
    return texts.length > MAX_NAMED_STATES ? `${texts.length} selected` : texts.join(", ");
});

function updateStates(values: string[]) {
    emit(
        "update:states",
        stateOptions.value.filter((option) => values.includes(option.value)).flatMap((option) => option.states),
    );
}

const versionOptions = computed(() =>
    offeredOptions(
        (props.versionsAvailable ?? []).map(String),
        props.versions ?? [],
        (version) => versionLabel(Number(version)) || version,
    ).sort((a, b) => Number(a.value) - Number(b.value)),
);
// One version has nothing to choose between.
const showVersions = computed(
    () => props.versions !== undefined && (versionOptions.value.length > 1 || props.versions.length > 0),
);
</script>

<template>
    <div class="comparison-filters d-flex flex-wrap align-items-start mb-2">
        <GDropdown
            class="comparison-filter-states-menu mr-4"
            size="sm"
            variant="outline-primary"
            toggle-class="comparison-filter-states-toggle">
            <template v-slot:button-content>State: {{ statesSummary }}</template>
            <GDropdownForm form-class="px-3 py-1">
                <GCheckboxGroup
                    :model-value="checkedStates"
                    class="comparison-filter-states"
                    aria-label="State"
                    :options="stateOptions"
                    size="small"
                    @update:model-value="updateStates" />
            </GDropdownForm>
        </GDropdown>
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

<style scoped lang="scss">
.comparison-filter-states :deep(.g-checkbox-group-options) {
    display: grid;
    grid-template-columns: repeat(2, max-content);
}
</style>
