import { computed, type Ref, ref } from "vue";

import type { ToolFormBatchInputCount, ToolFormJobExpansion } from "@/api/tools";
import type { FormData, FormInputNode } from "@/components/Form/composables/useFormState";
import { type EnclosingInput, findInputPathByDottedName, repeatTitle } from "@/components/Form/utilities";
import localize from "@/utils/localization";

export interface JobCountNotice {
    /** `info` notices go to a polite live region; `warning` notices render as alerts. */
    variant: "info" | "muted" | "warning";
    kind: "count" | "notReady" | "empty" | "mismatch" | "remap";
    text: string;
    detail?: string;
}

const REMAP_SEVERAL_JOBS = "Remapping replaces a single job, but this request would run several jobs.";

/** Title of a section or repeat block as the form shows it; conditionals show no title of their own. */
function enclosingTitle({ node, index }: EnclosingInput): string | undefined {
    if (node.type === "section") {
        return node.title || node.name;
    }
    if (node.type === "repeat" && index !== undefined) {
        return repeatTitle(index, node.title);
    }
    return undefined;
}

/** Label of a batched input qualified by its sections and repeat blocks ("Section › Input"),
 * falling back to its flat (`|`-separated) name. */
function batchInputLabel(inputs: FormInputNode[] | undefined, name: string): string {
    const found = findInputPathByDottedName(inputs ?? [], name);
    if (!found) {
        return name;
    }
    const titles = found.parents.map(enclosingTitle).filter((title): title is string => Boolean(title));
    return [...titles, found.node.label || name].join(" › ");
}

/** "A, B (12 each) × C (3)": matched inputs share a count, multiplied ones multiply it. */
function breakdown(inputs: ToolFormBatchInputCount[], label: (name: string) => string) {
    const groups: string[] = [];
    const matched = inputs.filter((i) => i.linked);
    if (matched.length > 1) {
        groups.push(`${matched.map((i) => label(i.name)).join(", ")} (${matched[0]!.count} ${localize("each")})`);
    } else if (matched.length === 1) {
        groups.push(`${label(matched[0]!.name)} (${matched[0]!.count})`);
    }
    for (const input of inputs.filter((i) => !i.linked)) {
        groups.push(`${label(input.name)} (${input.count})`);
    }
    return groups.join(" × ");
}

/** Notices describing the jobs a batched tool request will create; empty when there is nothing to say. */
export function jobCountNotices(
    expansion: ToolFormJobExpansion | undefined,
    inputs: FormInputNode[] | undefined,
    remapping = false,
): JobCountNotice[] {
    if (!expansion) {
        return [];
    }
    const label = (name: string) => batchInputLabel(inputs, name);
    const notices: JobCountNotice[] = [];
    const { job_count: jobCount, reason } = expansion;
    if (jobCount === 0) {
        const empty = expansion.inputs.filter((i) => i.count === 0).map((i) => label(i.name));
        notices.push({
            variant: "warning",
            kind: "empty",
            text: empty.length
                ? `${localize("No jobs will run because a batch input is empty:")} ${empty.join(", ")}.`
                : localize("No jobs will run because a batch input is empty."),
        });
    } else if (jobCount !== null && jobCount > 1) {
        notices.push({
            variant: "info",
            kind: "count",
            text: `${localize("This will run")} ${jobCount} ${localize("jobs.")}`,
            detail:
                expansion.inputs.length > 1
                    ? `${localize("Batch inputs:")} ${breakdown(expansion.inputs, label)}`
                    : undefined,
        });
        if (remapping) {
            notices.push({
                variant: "warning",
                kind: "remap",
                text: localize(REMAP_SEVERAL_JOBS),
            });
        }
    } else if (reason === "inputs_not_ready") {
        notices.push({
            variant: "muted",
            kind: "notReady",
            text: localize("Job count will be available once the selected collection is ready."),
        });
    } else if (reason === "batch_mismatch") {
        const matched = expansion.inputs.filter((i) => i.linked);
        const sizesDiffer = new Set(matched.map((i) => i.count)).size > 1;
        notices.push({
            variant: "warning",
            kind: "mismatch",
            text: sizesDiffer
                ? `${localize("Batch inputs must have matching sizes:")} ${matched
                      .map((i) => `${label(i.name)} (${i.count})`)
                      .join(", ")}.`
                : `${localize("Batch inputs cannot be matched because their collections have different structures:")} ${matched
                      .map((i) => label(i.name))
                      .join(", ")}.`,
        });
    }
    return notices;
}

/** Why Run should stay disabled: the server preview says the request would be rejected. */
export function runBlockedReason(expansion: ToolFormJobExpansion | undefined, remapping = false): string | undefined {
    if (!expansion) {
        return undefined;
    }
    const { job_count: jobCount, reason } = expansion;
    if (reason === "batch_mismatch") {
        return localize("Batch inputs must match before the tool can run.");
    }
    if (remapping && jobCount !== null && jobCount > 1) {
        return localize(REMAP_SEVERAL_JOBS);
    }
    return undefined;
}

/** Whether a preview built from `builtFrom` still describes `current`: some edits (e.g. conditional
 * switches) change batched inputs without rebuilding the form. */
function jobExpansionIsCurrent(
    expansion: ToolFormJobExpansion,
    builtFrom: FormData | undefined,
    current: FormData | undefined,
): boolean {
    if (!builtFrom) {
        return true;
    }
    return expansion.inputs.every(({ name }) => JSON.stringify(builtFrom[name]) === JSON.stringify(current?.[name]));
}

/** The server's job-count preview for a tool form, kept with the inputs it was built from so it can
 * be dropped once those inputs change, and the Run block it implies. */
export function useJobExpansion(
    formData: Ref<FormData | undefined>,
    invalidInput: Ref<string | undefined>,
    remapping: Ref<boolean>,
) {
    const preview = ref<{ expansion: ToolFormJobExpansion; builtFrom?: FormData }>();

    /** Record a build response's preview; `builtFrom` is the form data it was requested with. */
    function setJobExpansion(expansion?: ToolFormJobExpansion, builtFrom?: FormData) {
        preview.value = expansion ? { expansion, builtFrom } : undefined;
    }

    const jobExpansion = computed(() => {
        if (!preview.value) {
            return undefined;
        }
        const { expansion, builtFrom } = preview.value;
        if (!jobExpansionIsCurrent(expansion, builtFrom, formData.value)) {
            return undefined;
        }
        // A client-side error on a batched input already flags the mismatch at that field.
        if (expansion.reason === "batch_mismatch" && expansion.inputs.some((i) => i.name === invalidInput.value)) {
            return undefined;
        }
        return expansion;
    });

    const runBlocked = computed(() => runBlockedReason(jobExpansion.value, remapping.value));

    return { jobExpansion, runBlocked, setJobExpansion };
}
