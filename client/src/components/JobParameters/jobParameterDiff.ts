import { diffArrays } from "diff";

import type { components } from "@/api/schema";

export type JobParameter = components["schemas"]["JobParameter"];

export interface JobParameterDiffEntry {
    /** Unique per entry. */
    key: string;
    /** Heading labels and this one, e.g. `Section › Mode`. */
    path: string;
    label: string;
    depth: number;
    /** The value in each job as text; undefined when that job lacks the parameter. */
    a?: string;
    b?: string;
    /** Each job's note on the parameter, e.g. that it was added after the job ran. */
    notesA?: string;
    notesB?: string;
    differs: boolean;
}

interface Pathed {
    path: string;
    parameter: JobParameter;
    identity: string;
}

function valueText(value: JobParameter["value"]): string {
    if (Array.isArray(value)) {
        return value.map((item) => (item ? `${item.hid ?? "?"}: ${item.name}` : "")).join(", ");
    }
    return value === null || value === undefined ? "" : String(value);
}

/** Datasets compare by id, so two inputs with the same name still differ. */
function valueIdentity(value: JobParameter["value"]): string {
    if (Array.isArray(value)) {
        return JSON.stringify(value.map((item) => (item ? `${item.src}:${item.id}` : null)));
    }
    return JSON.stringify(value ?? null);
}

/** Sections and conditional test rows can head deeper rows; plain parameters carry notes, datasets a list. */
function canHead(parameter: JobParameter): boolean {
    return (parameter.notes === null || parameter.notes === undefined) && !Array.isArray(parameter.value);
}

/** Each parameter with the labels heading it; no row heads a repeat's members. */
function withPaths(parameters: JobParameter[]): Pathed[] {
    const heads: (string | undefined)[] = [];
    return parameters.map((parameter) => {
        heads.length = Math.max(parameter.depth - 1, 0);
        const path = [...heads, parameter.text].filter((label) => label !== undefined).join(" › ");
        heads.push(canHead(parameter) ? parameter.text : undefined);
        return { path, parameter, identity: valueIdentity(parameter.value) };
    });
}

function diffEntry(key: string, left?: Pathed, right?: Pathed): JobParameterDiffEntry {
    const { path, parameter } = (left ?? right)!;
    return {
        key,
        path,
        label: parameter.text,
        depth: parameter.depth,
        a: left && valueText(left.parameter.value),
        b: right && valueText(right.parameter.value),
        notesA: left?.parameter.notes || undefined,
        notesB: right?.parameter.notes || undefined,
        differs: !left || !right || left.identity !== right.identity,
    };
}

/**
 * Two jobs' `parameters_display` lists, in order. A sequence diff finds the unchanged runs; within each
 * changed stretch, parameters pair by path, and the second job's leftovers follow the first's.
 * Repeat members after a conditional's children share their path, so only the sequence keeps them apart.
 */
export function diffJobParameters(a: JobParameter[], b: JobParameter[]): JobParameterDiffEntry[] {
    const left = withPaths(a);
    const right = withPaths(b);
    const entries: JobParameterDiffEntry[] = [];
    let i = 0;
    let j = 0;
    let startA = 0;
    let startB = 0;

    const flushChanged = () => {
        const unpaired = right.slice(startB, j).map((_, offset) => startB + offset);
        for (let k = startA; k < i; k++) {
            const match = unpaired.findIndex((index) => right[index]!.path === left[k]!.path);
            const other = match === -1 ? undefined : unpaired.splice(match, 1)[0]!;
            entries.push(diffEntry(`a${k}`, left[k], other === undefined ? undefined : right[other]));
        }
        unpaired.forEach((index) => entries.push(diffEntry(`b${index}`, undefined, right[index])));
    };

    const changes = diffArrays(left, right, {
        comparator: (x, y) => x.path === y.path && x.identity === y.identity,
    });
    for (const change of changes) {
        if (change.removed) {
            i += change.count;
        } else if (change.added) {
            j += change.count;
        } else {
            flushChanged();
            for (let k = 0; k < change.count; k++, i++, j++) {
                entries.push(diffEntry(`a${i}`, left[i], right[j]));
            }
            startA = i;
            startB = j;
        }
    }
    flushChanged();
    return entries;
}
