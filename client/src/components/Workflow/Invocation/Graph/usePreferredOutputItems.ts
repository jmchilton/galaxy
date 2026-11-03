import { computed, type InjectionKey, type Ref, watch } from "vue";

import type { GraphStep, InvocationOutputItem } from "@/composables/useInvocationGraph";
import { useInvocationStore } from "@/stores/invocationStore";

import { stepOutputItem, useStepDetailsRefetch } from "./useStepOutputItems";

/** The dataset or collection each step is shown as, keyed by step id */
export type PreferredOutputItems = Record<number, InvocationOutputItem>;

/** The steps of an invocation graph that are shown as their preferred output, provided to the graph's nodes */
export const PREFERRED_OUTPUT_ITEMS: InjectionKey<Readonly<Ref<PreferredOutputItems>>> = Symbol("preferredOutputItems");

/** The output a step can be shown as: a tool step's preferred output, when the step has an output by that name */
export function preferredOutputName(step: GraphStep): string | undefined {
    const name = step.preferred_output;
    return step.type === "tool" && name && step.outputs.some((output) => output.name === name) ? name : undefined;
}

/** Which steps are shown as their preferred output, and as which dataset or collection.
 *
 * While enabled, every step that names a preferred output (see `preferredOutputName`) is shown as it once the
 * output exists. The invocation lists only workflow outputs (`GraphStep.outputItems`); for any other output the
 * step's details are fetched, and fetched again when the step's state changes while the output is still missing.
 * @param steps - The invocation graph's steps
 * @param enabled - Whether steps are shown as their preferred output
 * @param detailedStepId - The step drawn with its connections instead of as an invocation step, if any
 */
export function usePreferredOutputItems(
    steps: Ref<Record<string, GraphStep>>,
    enabled: Ref<boolean>,
    detailedStepId: () => number | null = () => null,
) {
    const invocationStore = useInvocationStore();

    /** The steps that can be shown as their preferred output right now, with its name */
    const candidates = computed(() =>
        enabled.value
            ? Object.values(steps.value).flatMap((step) => {
                  const name = preferredOutputName(step);
                  return name && step.id !== detailedStepId() ? [{ step, name }] : [];
              })
            : [],
    );

    const items = computed(() => {
        const items: PreferredOutputItems = {};
        for (const { step, name } of candidates.value) {
            const item = stepOutputItem(invocationStore, step, name);
            if (item) {
                items[step.id] = item;
            }
        }
        return items;
    });

    const refetch = useStepDetailsRefetch(invocationStore);
    const missing = computed(() =>
        candidates.value
            .filter(({ step }) => step.invocationStepId && !items.value[step.id])
            .map(({ step }) => ({ invocationStepId: step.invocationStepId!, state: step.state })),
    );
    watch(
        () => missing.value.map(({ invocationStepId, state }) => `${invocationStepId}:${state}`).join(","),
        () => {
            for (const { invocationStepId, state } of missing.value) {
                refetch(invocationStepId, state);
            }
        },
        { immediate: true },
    );

    return { items };
}
