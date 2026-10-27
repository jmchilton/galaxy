import type { LocationQuery, LocationQueryValue } from "vue-router";

import type { ComparisonKind, ComparisonQuery, ComparisonRequest } from "@/api/comparisons";

/** Rows per page when the URL names no `limit`; the server's default too. */
export const DEFAULT_LIMIT = 25;
export const PAGE_SIZES = [10, 25, 50, 100];

export type ParsedComparison = ComparisonRequest | { kind?: undefined; error: string };

/** A `/comparisons` URL query value; empty values are dropped. */
export type ComparisonUrlValue = string | number | boolean | (string | null)[] | null | undefined;

const LIST_KEYS = new Set(["states", "metadata_elements", "tool_versions", "output_labels"]);
const NUMBER_KEYS = new Set(["limit", "offset"]);
const BOOLEAN_KEYS = new Set(["instance", "sort_desc", "inline_expression_values", "include_workflow_jobs"]);
const REQUIRED: Record<ComparisonKind, string[]> = {
    step_runs: ["workflow_id", "step_label"],
    output_runs: ["workflow_id"],
    tool_runs: ["tool_id"],
};

function isKind(kind: unknown): kind is ComparisonKind {
    return typeof kind === "string" && kind in REQUIRED;
}

function first(value: LocationQueryValue | LocationQueryValue[] | undefined): string | undefined {
    const single = Array.isArray(value) ? value[0] : value;
    return single ?? undefined;
}

function parseValue(key: string, value: LocationQueryValue | LocationQueryValue[]): unknown {
    if (LIST_KEYS.has(key)) {
        return (Array.isArray(value) ? value : [value]).filter((item): item is string => item !== null);
    }
    const single = first(value);
    if (single === undefined) {
        return undefined;
    }
    if (NUMBER_KEYS.has(key)) {
        const number = Number(single);
        return Number.isInteger(number) ? number : single;
    }
    if (BOOLEAN_KEYS.has(key)) {
        return single === "true" ? true : single === "false" ? false : single;
    }
    return single;
}

/** Turns `/comparisons` URL query into the matching endpoint's parameters, forwarding every key but `kind`. */
export function parseComparisonQuery(query: LocationQuery): ParsedComparison {
    const kind = first(query.kind);
    if (!isKind(kind)) {
        return { error: kind ? `Unknown comparison kind "${kind}".` : "No comparison kind given." };
    }
    const missing = REQUIRED[kind].filter((key) => !first(query[key]));
    if (missing.length) {
        return { error: `A ${kind} comparison needs ${missing.join(" and ")}.` };
    }
    const params: Record<string, unknown> = {};
    for (const [key, value] of Object.entries(query)) {
        const parsed = key === "kind" ? undefined : parseValue(key, value);
        if (parsed !== undefined) {
            params[key] = parsed;
        }
    }
    return { kind, params } as ComparisonRequest;
}

/** Drops keys whose value is unset or an empty list. */
export function cleanUrlQuery(query: Record<string, ComparisonUrlValue>): Record<string, string | (string | null)[]> {
    const clean: Record<string, string | (string | null)[]> = {};
    for (const [key, value] of Object.entries(query)) {
        if (value === undefined || value === null || (Array.isArray(value) && !value.length)) {
            continue;
        }
        clean[key] = Array.isArray(value) ? value : String(value);
    }
    return clean;
}

/** A `/comparisons` link; list values repeat their key, never comma-joined. */
export function comparisonPath(kind: ComparisonKind, query: Record<string, ComparisonUrlValue>): string {
    const search = new URLSearchParams({ kind });
    for (const [key, value] of Object.entries(cleanUrlQuery(query))) {
        (Array.isArray(value) ? value : [value]).forEach((item) => item !== null && search.append(key, item));
    }
    return `/comparisons?${search.toString()}`;
}

/** Local-storage key for display preferences; the step tab and the page share it. */
export function displayStorageKey(query: ComparisonQuery): string {
    switch (query.kind) {
        case "step_runs":
            return `step_runs:${query.workflow_id}:${query.step_label}`;
        case "output_runs":
            return `output_runs:${query.workflow_id}`;
        default:
            return `tool_runs:${query.tool_id}`;
    }
}

/** States offered by the state filter: job states for steps and tools, invocation states for workflows. */
export const STATE_OPTIONS: Record<ComparisonKind, string[]> = {
    step_runs: ["new", "queued", "running", "ok", "error", "paused", "skipped", "deleted"],
    output_runs: ["new", "ready", "scheduled", "completed", "failed", "cancelled"],
    tool_runs: ["new", "queued", "running", "ok", "error", "paused", "skipped", "deleted"],
};
