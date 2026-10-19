<script setup lang="ts">
import { type Component, computed, type ComputedRef } from "vue";

import localize from "@/utils/localization";

import { getAllValues, type Option, type Value } from "./utilities";

import FormDrilldownList from "./FormDrilldownList.vue";
import GAlert from "@/components/BaseComponents/GAlert.vue";
import GCheckbox from "@/components/BaseComponents/GCheckbox.vue";
import GCheckboxGroup from "@/components/BaseComponents/GCheckboxGroup.vue";
import GRadioGroup from "@/components/BaseComponents/GRadioGroup.vue";

const props = withDefaults(
    defineProps<{
        id: string;
        value?: Value;
        options: Array<Option>;
        multiple: boolean;
        showIcons?: boolean;
        /** Id of the element naming the group */
        ariaLabelledby?: string;
    }>(),
    {
        value: null,
        showIcons: false,
        ariaLabelledby: undefined,
    },
);

const emit = defineEmits<{
    (e: "input", value: Value): void;
}>();

const hasOptions = computed(() => {
    return props.options.length > 0;
});

// Determine all available values
const allValues: ComputedRef<string[]> = computed(() => {
    return getAllValues(props.options);
});

// Determine current value
const currentValue: ComputedRef<string[]> = computed(() => {
    if (props.value === null || props.value === "") {
        return [];
    } else if (Array.isArray(props.value)) {
        return props.value;
    } else {
        return [props.value];
    }
});

// The group owns the selection state, name and toggling for the options at every depth
const groupComponent: ComputedRef<Component> = computed(() => (props.multiple ? GCheckboxGroup : GRadioGroup));

// Determine if select all is checked
const selectAllChecked: ComputedRef<boolean> = computed(() => {
    return allValues.value.length === currentValue.value.length;
});

// Determine if select all state undetermined
const selectAllIndeterminate: ComputedRef<boolean> = computed(() => {
    return ![0, allValues.value.length].includes(currentValue.value.length);
});

// Only the chosen option is submitted; the server expands a recurse hierarchy
function onInput(value: string | string[]): void {
    emit("input", Array.isArray(value) && value.length === 0 ? null : value);
}

// Handle click on select all checkbox to either select or unselect all values
function onSelectAll(selected: boolean): void {
    emit("input", selected ? allValues.value : null);
}
</script>

<template>
    <div>
        <div v-if="hasOptions">
            <GCheckbox
                v-if="multiple"
                class="select-all-checkbox"
                :indeterminate="selectAllIndeterminate"
                :model-value="selectAllChecked"
                @update:model-value="onSelectAll">
                {{ localize("Select / Deselect All") }}
            </GCheckbox>

            <component
                :is="groupComponent"
                stacked
                :aria-labelledby="ariaLabelledby"
                :model-value="multiple ? currentValue : currentValue[0]"
                @update:model-value="onInput">
                <FormDrilldownList
                    :show-icons="showIcons"
                    :multiple="multiple"
                    :current-value="currentValue"
                    :options="options" />
            </component>
        </div>
        <div v-else>
            <GAlert show variant="info" class="mt-2"> No options available. </GAlert>
        </div>
    </div>
</template>
