import { computed, type Ref } from "vue";

import type { GraphStep, GraphStepState, InvocationOutputItem } from "@/composables/useInvocationGraph";
import { useInvocationStore } from "@/stores/invocationStore";

/** Every produced output of an invocation graph step, keyed by output name.
 *
 * The invocation lists only workflow inputs and outputs (`GraphStep.outputItems`). When those don't cover every
 * output, reading `items` fetches the step's details once, and `load()` fetches them again once the step's state
 * has changed, e.g. after the step has run and created its outputs.
 * @param step - The invocation graph step
 */
export function useStepOutputItems(step: Ref<GraphStep>) {
    const invocationStore = useInvocationStore();

    const listedItems = computed(() => step.value.outputItems ?? {});
    const allListed = computed(() => step.value.outputs.every((output) => listedItems.value[output.name]));

    const items = computed<Record<string, InvocationOutputItem>>(() => {
        const invocationStepId = step.value.invocationStepId;
        if (allListed.value || !invocationStepId) {
            return listedItems.value;
        }
        const details = invocationStore.getInvocationStepById(invocationStepId);
        const merged = { ...listedItems.value };
        for (const [name, output] of [
            ...Object.entries(details?.outputs ?? {}),
            ...Object.entries(details?.output_collections ?? {}),
        ]) {
            merged[name] ??= { src: output.src, id: output.id };
        }
        return merged;
    });

    const loading = computed(() => {
        const invocationStepId = step.value.invocationStepId;
        return !!invocationStepId && invocationStore.isLoadingInvocationStep(invocationStepId);
    });

    /** The step's state when `load()` last fetched its details; some outputs never appear, e.g. filtered ones */
    let fetchedUnderState: GraphStepState | undefined;

    function load() {
        const { invocationStepId, outputs, state } = step.value;
        const missing = outputs.some((output) => !items.value[output.name]);
        if (invocationStepId && missing && state !== fetchedUnderState) {
            fetchedUnderState = state;
            invocationStore.fetchInvocationStepById({ id: invocationStepId });
        }
    }

    return {
        /** The dataset or collection produced for each output that has one */
        items,
        /** Whether the step's details are being fetched */
        loading,
        /** Fetch the step's details again if any output is still missing and the step's state has changed */
        load,
    };
}
