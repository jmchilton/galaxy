import { computed, type Ref } from "vue";

import type { GraphStep, GraphStepState, InvocationOutputItem } from "@/composables/useInvocationGraph";
import { useInvocationStore } from "@/stores/invocationStore";

type InvocationStore = ReturnType<typeof useInvocationStore>;

/** The dataset or collection produced for a step's output, if any.
 *
 * The invocation lists only workflow inputs and outputs (`GraphStep.outputItems`); any other output comes from the
 * step's details, which reading fetches once. Returns the stored object itself rather than a copy, so reevaluating
 * a computed over it doesn't re-render the output's previews.
 */
export function stepOutputItem(
    invocationStore: InvocationStore,
    step: GraphStep,
    name: string,
): InvocationOutputItem | undefined {
    const listed = step.outputItems?.[name];
    if (listed || !step.invocationStepId) {
        return listed;
    }
    const details = invocationStore.getInvocationStepById(step.invocationStepId);
    return details?.outputs?.[name] ?? details?.output_collections?.[name];
}

/** Fetches a step's details again, at most once per state of the step: an output still missing after the step's
 * state changed (e.g. after it ran) may exist now, while some outputs never appear (e.g. filtered ones). */
export function useStepDetailsRefetch(invocationStore: InvocationStore) {
    const fetchedUnderState = new Map<string, GraphStepState>();
    return function refetch(invocationStepId: string, state: GraphStepState) {
        if (fetchedUnderState.get(invocationStepId) !== state) {
            fetchedUnderState.set(invocationStepId, state);
            invocationStore.fetchInvocationStepById({ id: invocationStepId });
        }
    };
}

/** Every produced output of an invocation graph step, keyed by output name.
 *
 * Reading `items` fetches the step's details once when the invocation doesn't list every output (see
 * `stepOutputItem`), and `load()` fetches them again once the step's state has changed.
 * @param step - The invocation graph step
 */
export function useStepOutputItems(step: Ref<GraphStep>) {
    const invocationStore = useInvocationStore();
    const refetch = useStepDetailsRefetch(invocationStore);

    const items = computed(() => {
        const items: Record<string, InvocationOutputItem> = {};
        for (const output of step.value.outputs) {
            const item = stepOutputItem(invocationStore, step.value, output.name);
            if (item) {
                items[output.name] = item;
            }
        }
        return items;
    });

    const loading = computed(() => {
        const invocationStepId = step.value.invocationStepId;
        return !!invocationStepId && invocationStore.isLoadingInvocationStep(invocationStepId);
    });

    function load() {
        const { invocationStepId, outputs, state } = step.value;
        if (invocationStepId && outputs.some((output) => !items.value[output.name])) {
            refetch(invocationStepId, state);
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
