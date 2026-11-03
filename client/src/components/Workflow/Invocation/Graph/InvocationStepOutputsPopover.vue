<script setup lang="ts">
import { computed, ref, toRef, watch } from "vue";

import type { GraphStep } from "@/composables/useInvocationGraph";

import { useStepOutputItems } from "./useStepOutputItems";

import GPopover from "@/components/BaseComponents/GPopover.vue";
import LoadingSpan from "@/components/LoadingSpan.vue";
import InvocationOutputPreview from "@/components/Workflow/Invocation/Graph/InvocationOutputPreview.vue";

const props = defineProps<{
    /** The invocation graph step whose outputs are previewed */
    step: GraphStep;
    /** The element hovering opens the popover from */
    target: () => Element | undefined;
}>();

const show = ref(false);
const { items, loading, load } = useStepOutputItems(toRef(props, "step"));

// a parameter input's value is already shown on its node
const previewable = computed(
    () => !!props.step.invocationStepId && props.step.type !== "parameter_input" && props.step.outputs.length > 0,
);

/** Whether the previews are mounted. They load nothing until the first hover, then stay mounted between hovers,
 * so hovering again doesn't reload them, until the step's state changes while they're hidden. */
const previewsMounted = ref(false);

watch([show, () => props.step.state], ([shown, state], [, oldState]) => {
    if (shown) {
        previewsMounted.value = true;
        // on opening, or a state change while shown (e.g. the job finished), outputs may have been created
        load();
    } else if (state !== oldState) {
        previewsMounted.value = false;
    }
});

const previews = computed(() =>
    props.step.outputs.flatMap((output) => {
        const item = items.value[output.name];
        const label = props.step.workflow_outputs?.find((wo) => wo.output_name === output.name)?.label;
        return item ? [{ name: output.name, label: label || output.name, item }] : [];
    }),
);
</script>

<template>
    <!-- not `interactive`: the output terminal it hangs from is a plain element, not a button or link -->
    <GPopover
        v-if="previewable"
        v-model:show="show"
        :target="props.target"
        triggers="hover"
        placement="right"
        custom-class="invocation-step-outputs-popover">
        <div v-if="previewsMounted" data-description="invocation step outputs" :data-open="show">
            <div
                v-for="preview in previews"
                :key="preview.name"
                class="invocation-step-output"
                :data-output-name="preview.name">
                <div class="font-weight-bold mb-1" data-description="invocation step output label">
                    {{ preview.label }}
                </div>
                <InvocationOutputPreview :item="preview.item" :step="props.step" />
            </div>
            <LoadingSpan v-if="!previews.length && loading" message="Loading outputs" />
            <div v-else-if="!previews.length" class="text-muted">No outputs produced yet.</div>
        </div>
    </GPopover>
</template>

<style lang="scss">
.invocation-step-outputs-popover {
    width: max-content;
    min-width: 16rem;
    max-width: min(40rem, 90vw);

    .popover-body {
        max-height: 25rem;
        overflow: auto;
    }

    .invocation-step-output + .invocation-step-output {
        margin-top: 0.5rem;
    }
}
</style>
