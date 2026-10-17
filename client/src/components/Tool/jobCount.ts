import type { ToolFormBatchInputCount, ToolFormJobExpansion } from "@/api/tools";
import type { FormInputNode } from "@/components/Form/composables/useFormState";
import { repeatTitle, visitInputs } from "@/components/Form/utilities";
import localize from "@/utils/localization";

export interface JobCountNotice {
    /** `info` notices go to a polite live region; `warning` notices render as alerts. */
    variant: "info" | "muted" | "warning";
    kind: "count" | "notReady" | "empty" | "mismatch" | "remap";
    text: string;
    detail?: string;
}

interface EnclosingInput {
    node: FormInputNode;
    index?: number;
}

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
    let label = name;
    visitInputs(inputs ?? [], (node: FormInputNode, nodeName: string, _context: unknown, parents: EnclosingInput[]) => {
        if (nodeName === name && (node.type === "data" || node.type === "data_collection")) {
            const titles = parents.map(enclosingTitle).filter((title): title is string => Boolean(title));
            label = [...titles, node.label || name].join(" › ");
        }
    });
    return label;
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
                text: localize(
                    "Remapping replaces a single job, but this request would run several jobs and will be rejected.",
                ),
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

/** Why Run should stay disabled: the server preview says the request would run nothing or be rejected. */
export function runBlockedReason(expansion: ToolFormJobExpansion | undefined, remapping = false): string | undefined {
    if (!expansion) {
        return undefined;
    }
    const { job_count: jobCount, reason } = expansion;
    if (jobCount === 0) {
        return localize("No jobs would run because a batch input is empty.");
    }
    if (reason === "batch_mismatch") {
        return localize("Batch inputs must match before the tool can run.");
    }
    if (remapping && jobCount !== null && jobCount > 1) {
        return localize("Remapping replaces a single job, but this request would run several jobs.");
    }
    return undefined;
}
