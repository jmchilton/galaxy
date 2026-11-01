<template>
    <!-- Space activates on keyup, like a native button, so a handler that moves focus cannot also activate the newly focused control. -->
    <div
        role="button"
        tabindex="0"
        @click="$emit('click')"
        @keydown.enter.prevent="$emit('click')"
        @keydown.space.prevent
        @keyup.space="$emit('click')">
        <slot />
    </div>
</template>
