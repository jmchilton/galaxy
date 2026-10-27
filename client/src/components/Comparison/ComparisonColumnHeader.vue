<script setup lang="ts">
import { faCaretDown } from "@fortawesome/free-solid-svg-icons";
import { FontAwesomeIcon } from "@fortawesome/vue-fontawesome";
import { computed } from "vue";

import type { ComparisonColumn, ComparisonRow } from "@/api/comparisons";

import { type CellDisplay, displayLabel, displayOptions, ROLE_LABELS, versionLabel } from "./comparisonUtils";

import GDropdown from "@/components/BaseComponents/GDropdown.vue";
import GDropdownGroup from "@/components/BaseComponents/GDropdownGroup.vue";
import GDropdownItem from "@/components/BaseComponents/GDropdownItem.vue";

const props = defineProps<{
    column: ComparisonColumn;
    rows: ComparisonRow[];
    display: CellDisplay;
}>();

const emit = defineEmits<{
    (e: "update:display", display: CellDisplay): void;
}>();

const options = computed(() => displayOptions(props.column, props.rows));
const valueOptions = computed(() => options.value.filter((option) => !option.display.startsWith("meta:")));
const metadataOptions = computed(() => options.value.filter((option) => option.display.startsWith("meta:")));

const versions = computed(() => props.column.present_in_versions?.map(versionLabel) ?? []);
const versionsTitle = computed(() => `Only runs of ${versions.value.join(", ")} have this ${props.column.role}`);

function choose(display: CellDisplay, disabled?: boolean) {
    if (!disabled && display !== props.display) {
        emit("update:display", display);
    }
}
</script>

<template>
    <span class="comparison-column-header">
        <span class="d-inline-flex align-items-center flex-wrap">
            <span class="comparison-role badge" :class="`comparison-role-${column.role}`" :title="column.role">
                {{ ROLE_LABELS[column.role] }}
            </span>
            <code class="comparison-column-label">{{ column.label }}</code>
            <span v-if="versions.length" class="badge badge-warning ml-1" :title="versionsTitle">
                {{ versions.length === 1 ? `${versions[0]} only` : `in ${versions.join(", ")}` }}
            </span>
            <span
                v-if="column.duplicate"
                class="badge badge-warning ml-1"
                title="More than one output has this label in some version; showing the first">
                duplicate label
            </span>
            <GDropdown
                size="sm"
                variant="link"
                no-caret
                toggle-class="comparison-column-menu p-0 ml-1"
                :aria-label="`Cell display for ${column.label}`">
                <template v-slot:button-content>
                    <FontAwesomeIcon :icon="faCaretDown" />
                </template>
                <GDropdownGroup aria-label="Show in cells">
                    <template v-slot:header>Show in cells</template>
                    <GDropdownItem
                        v-for="option in valueOptions"
                        :key="option.display"
                        role="menuitemradio"
                        :aria-checked="display === option.display ? 'true' : 'false'"
                        :active="display === option.display"
                        :disabled="option.disabled"
                        @click="choose(option.display, option.disabled)">
                        {{ option.label }}
                    </GDropdownItem>
                </GDropdownGroup>
                <GDropdownGroup v-if="metadataOptions.length" aria-label="Metadata element">
                    <template v-slot:header>Metadata element</template>
                    <GDropdownItem
                        v-for="option in metadataOptions"
                        :key="option.display"
                        role="menuitemradio"
                        :aria-checked="display === option.display ? 'true' : 'false'"
                        :active="display === option.display"
                        @click="choose(option.display)">
                        <code>{{ option.label }}</code>
                    </GDropdownItem>
                </GDropdownGroup>
            </GDropdown>
        </span>
        <small class="comparison-showing d-block text-muted font-weight-normal">{{ displayLabel(display) }}</small>
    </span>
</template>

<style scoped lang="scss">
.comparison-role {
    font-size: 0.65rem;
    text-transform: uppercase;
    border: 1px solid currentColor;
    margin-right: 0.3rem;
}
.comparison-role-input {
    color: var(--color-blue-600);
}
.comparison-role-output {
    color: var(--color-green-700);
}
.comparison-role-parameter {
    color: var(--color-orange-700);
}
.comparison-column-label {
    color: inherit;
}
</style>
