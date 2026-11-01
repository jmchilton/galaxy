<script setup lang="ts">
import { ref } from "vue";

const emit = defineEmits<{
    (e: "click"): void;
}>();

// Like a native button, Space activates on keyup, and only if the press started here.
// A handler that moves focus then cannot also activate the newly focused control.
const spacePressed = ref(false);

function onSpaceUp() {
    if (spacePressed.value) {
        spacePressed.value = false;
        emit("click");
    }
}
</script>

<template>
    <div
        role="button"
        tabindex="0"
        @blur="spacePressed = false"
        @click="emit('click')"
        @keydown.enter.prevent="emit('click')"
        @keydown.space.prevent="spacePressed = true"
        @keyup.space="onSpaceUp">
        <slot />
    </div>
</template>
