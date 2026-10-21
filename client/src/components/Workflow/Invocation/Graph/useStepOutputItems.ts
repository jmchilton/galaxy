import { computed, type Ref } from "vue";

import type { GraphStep, InvocationOutputItem } from "@/composables/useInvocationGraph";
import { useInvocationStore } from "@/stores/invocationStore";

/** Every produced output of an invocation graph step. The invocation only lists workflow inputs and
 * outputs, so `load()` fetches the step's details for the rest.
 */
export function useStepOutputItems(step: Ref<GraphStep | undefined>) {
    const invocationStore = useInvocationStore();

    const items = computed<Record<string, InvocationOutputItem>>(() => {
        const graphStep = step.value;
        const merged: Record<string, InvocationOutputItem> = { ...graphStep?.outputItems };
        const details = graphStep?.invocationStepId
            ? invocationStore.getInvocationStepById(graphStep.invocationStepId)
            : undefined;
        for (const [name, output] of Object.entries(details?.outputs ?? {})) {
            merged[name] ??= { src: "hda", id: output.id };
        }
        for (const [name, output] of Object.entries(details?.output_collections ?? {})) {
            merged[name] ??= { src: "hdca", id: output.id };
        }
        return merged;
    });

    function load() {
        const graphStep = step.value;
        const missing = graphStep?.outputs.some((output) => !items.value[output.name]);
        if (graphStep?.invocationStepId && missing) {
            invocationStore.fetchInvocationStepById({ id: graphStep.invocationStepId });
        }
    }

    return { items, load };
}
