import type { components } from "@/api/schema";

export type JobParameter = components["schemas"]["JobParameter"];

export interface JobParameterDiffEntry {
    /** Unique per entry: the path and its occurrence. */
    key: string;
    /** Ancestor labels and this one, e.g. `Section › Mode`. */
    path: string;
    label: string;
    depth: number;
    /** The value in each job as text; undefined when that job lacks the parameter. */
    a?: string;
    b?: string;
    differs: boolean;
}

interface Keyed {
    key: string;
    path: string;
    parameter: JobParameter;
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

/** Each parameter keyed by its path through the nested list; repeated paths by occurrence. */
function keyed(parameters: JobParameter[]): Keyed[] {
    const ancestors: string[] = [];
    const seen = new Map<string, number>();
    return parameters.map((parameter) => {
        ancestors.length = Math.max(parameter.depth - 1, 0);
        const path = [...ancestors, parameter.text].join(" › ");
        ancestors.push(parameter.text);
        const count = (seen.get(path) ?? 0) + 1;
        seen.set(path, count);
        return { key: `${path}#${count}`, path, parameter };
    });
}

/** Two jobs' `parameters_display` lists, paired by path; the first job's order, then parameters only the second has. */
export function diffJobParameters(a: JobParameter[], b: JobParameter[]): JobParameterDiffEntry[] {
    const right = new Map(keyed(b).map((entry) => [entry.key, entry]));
    const entries: JobParameterDiffEntry[] = keyed(a).map(({ key, path, parameter }) => {
        const other = right.get(key)?.parameter;
        right.delete(key);
        return {
            key,
            path,
            label: parameter.text,
            depth: parameter.depth,
            a: valueText(parameter.value),
            b: other ? valueText(other.value) : undefined,
            differs: !other || valueIdentity(parameter.value) !== valueIdentity(other.value),
        };
    });
    for (const { key, path, parameter } of right.values()) {
        entries.push({
            key,
            path,
            label: parameter.text,
            depth: parameter.depth,
            b: valueText(parameter.value),
            differs: true,
        });
    }
    return entries;
}
