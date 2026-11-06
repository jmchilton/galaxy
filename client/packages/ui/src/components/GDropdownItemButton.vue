<script setup lang="ts">
/**
 * Button-style dropdown item (no link behavior).
 * Replaces BDropdownItemButton from bootstrap-vue.
 */

import { computed, inject } from "vue";

import { dropdownHideKey } from "./dropdownContext";

const props = withDefaults(
    defineProps<{
        active?: boolean;
        disabled?: boolean;
        variant?: string;
    }>(),
    {
        active: false,
        disabled: false,
        variant: undefined,
    },
);

const emit = defineEmits<{
    (e: "click", event: MouseEvent): void;
}>();

const hideDropdown = inject(dropdownHideKey, () => {});

const classes = computed(() => ({
    "dropdown-item": true,
    active: props.active,
    disabled: props.disabled,
    [`text-${props.variant}`]: !!props.variant,
}));

function onClick(event: MouseEvent) {
    if (props.disabled) {
        return;
    }
    emit("click", event);
    hideDropdown();
}
</script>

<template>
    <button
        type="button"
        :class="classes"
        :disabled="disabled"
        :aria-current="active ? 'true' : undefined"
        role="menuitem"
        tabindex="-1"
        @click="onClick">
        <slot />
    </button>
</template>

<style scoped lang="scss">
@use "../styles/focus-ring" as *;

.dropdown-item {
    cursor: pointer;
}

.dropdown-item:focus-visible {
    @include focus-ring-inset;
}
</style>
