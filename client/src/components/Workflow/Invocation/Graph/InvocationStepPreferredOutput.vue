<script setup lang="ts">
import { faSignOutAlt } from "@fortawesome/free-solid-svg-icons";
import { FontAwesomeIcon } from "@fortawesome/vue-fontawesome";
import { computed } from "vue";

import type { GraphStep, InvocationOutputItem } from "@/composables/useInvocationGraph";

import InvocationOutputSnapshot from "./InvocationOutputSnapshot.vue";

const props = defineProps<{
    /** The dataset or collection the step is shown as */
    item: InvocationOutputItem;
    /** The step shown as its preferred output */
    step: GraphStep;
}>();

/** The label its card would have had, when the output is a labelled workflow output, or else the output's name */
const label = computed(
    () =>
        props.step.workflow_outputs?.find((output) => output.output_name === props.step.preferred_output)?.label ||
        props.step.preferred_output,
);
</script>

<template>
    <!-- in place of the step's state, labelled like an embedded output card -->
    <div
        class="invocation-step-preferred-output"
        :class="{ 'preferred-output-collection': item.src === 'hdca' }"
        data-description="invocation step preferred output">
        <div class="preferred-output-label text-truncate" data-description="invocation step preferred output label">
            <FontAwesomeIcon :icon="faSignOutAlt" fixed-width />
            <span class="font-weight-bold">{{ label }}</span>
        </div>
        <InvocationOutputSnapshot class="preferred-output-snapshot" :item="item" :step="step" />
    </div>
</template>

<style scoped lang="scss">
@import "@/style/scss/theme/blue.scss";

// as tall as the body of an embedded output card (260×170, collections 260×120), label included
.invocation-step-preferred-output {
    display: flex;
    flex-direction: column;
    height: 8.5rem;
    // static, like the snapshot: clicks select the step, and drags and zooms move the graph
    pointer-events: none;

    &.preferred-output-collection {
        height: 5.25rem;
    }
}

.preferred-output-label {
    flex-shrink: 0;
    padding: 0.125rem 0.5rem 0;
    font-size: 0.75rem;
    color: $brand-primary;
}

.preferred-output-snapshot {
    flex: 1;
    min-height: 0;
}
</style>
