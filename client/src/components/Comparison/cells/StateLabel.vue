<script setup lang="ts">
import { FontAwesomeIcon } from "@fortawesome/vue-fontawesome";
import { computed } from "vue";

import { type GraphStepState, iconClasses, statePlaceholders } from "@/composables/useInvocationGraph";

const props = defineProps<{
    /** A job, dataset, collection or invocation state. */
    state: string;
    /** Show only the icon, naming the state in its title. */
    iconOnly?: boolean;
}>();

const icon = computed(() => iconClasses[props.state as GraphStepState]);
// The placeholder for failed_metadata only reads after a job count.
const text = computed(() =>
    props.state === "failed_metadata" ? props.state : (statePlaceholders[props.state] ?? props.state),
);
</script>

<template>
    <span :title="iconOnly ? text : undefined">
        <FontAwesomeIcon v-if="icon" :icon="icon.icon" :spin="icon.spin" :class="icon.class" fixed-width />
        <template v-if="!iconOnly">{{ text }}</template>
    </span>
</template>
