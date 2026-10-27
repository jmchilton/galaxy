import type { LocationQuery, LocationQueryValue } from "vue-router";

import type {
    ComparisonKind,
    ComparisonQuery,
    ComparisonRequest,
    OutputRunsParams,
    StepRunsParams,
    ToolRunsParams,
} from "@/api/comparisons";
import type { InvocationState } from "@/api/invocations";
import type { JobState } from "@/api/jobs";
import { versionlessToolId } from "@/utils/tool-version";

/** Rows per page when the URL names no `limit`; the server's default too. */
export const DEFAULT_LIMIT = 25;
export const PAGE_SIZES = [10, 25, 50, 100];

export type ParsedComparison = ComparisonRequest | { kind?: undefined; error: string };

/** A `/comparisons` URL query value; empty values are dropped. */
export type ComparisonUrlValue = string | number | boolean | (string | null)[] | null | undefined;

/** How a URL value becomes an endpoint parameter; lists repeat their key. */
type ParamKind = "string" | "number" | "boolean" | "list";
type ParamSpec<Params> = { readonly [Key in keyof Required<Params>]: ParamKind };

const COMMON_PARAMS = {
    limit: "number",
    offset: "number",
    sort_by: "string",
    sort_desc: "boolean",
    states: "list",
    metadata_elements: "list",
    inline_expression_values: "boolean",
} as const satisfies Record<keyof StepRunsParams & keyof OutputRunsParams & keyof ToolRunsParams, ParamKind>;

/** The URL keys each kind takes: its endpoint's parameters, and no others. */
const PARAMS = {
    step_runs: { ...COMMON_PARAMS, workflow_id: "string", instance: "boolean", step_label: "string" },
    output_runs: { ...COMMON_PARAMS, workflow_id: "string", instance: "boolean", output_labels: "list" },
    tool_runs: {
        ...COMMON_PARAMS,
        tool_id: "string",
        tool_versions: "list",
        history_id: "string",
        include_workflow_jobs: "boolean",
    },
} as const satisfies {
    step_runs: ParamSpec<StepRunsParams>;
    output_runs: ParamSpec<OutputRunsParams>;
    tool_runs: ParamSpec<ToolRunsParams>;
};

const REQUIRED = {
    step_runs: ["workflow_id", "step_label"],
    output_runs: ["workflow_id"],
    tool_runs: ["tool_id"],
} as const satisfies {
    step_runs: (keyof StepRunsParams)[];
    output_runs: (keyof OutputRunsParams)[];
    tool_runs: (keyof ToolRunsParams)[];
};

function isKind(kind: unknown): kind is ComparisonKind {
    return typeof kind === "string" && Object.hasOwn(PARAMS, kind);
}

function first(value: LocationQueryValue | LocationQueryValue[] | undefined): string | undefined {
    const single = Array.isArray(value) ? value[0] : value;
    return single ?? undefined;
}

function parseValue(paramKind: ParamKind, value: LocationQueryValue | LocationQueryValue[]): unknown {
    if (paramKind === "list") {
        return (Array.isArray(value) ? value : [value]).filter((item): item is string => item !== null);
    }
    const single = first(value);
    if (single === undefined) {
        return undefined;
    }
    // Malformed values go through unchanged, so the server's validation error is shown.
    if (paramKind === "number") {
        const number = Number(single);
        return Number.isInteger(number) ? number : single;
    }
    if (paramKind === "boolean") {
        return single === "true" ? true : single === "false" ? false : single;
    }
    return single;
}

/** Turns `/comparisons` URL query into the matching endpoint's parameters; rejects keys the endpoint doesn't take. */
export function parseComparisonQuery(query: LocationQuery): ParsedComparison {
    const kind = first(query.kind);
    if (!isKind(kind)) {
        return { error: kind ? `Unknown comparison kind "${kind}".` : "No comparison kind given." };
    }
    const spec: Record<string, ParamKind> = PARAMS[kind];
    const unsupported = Object.keys(query).filter((key) => key !== "kind" && !Object.hasOwn(spec, key));
    if (unsupported.length) {
        return { error: `A ${kind} comparison does not take ${unsupported.join(", ")}.` };
    }
    const missing = REQUIRED[kind].filter((key) => !first(query[key]));
    if (missing.length) {
        return { error: `A ${kind} comparison needs ${missing.join(" and ")}.` };
    }
    const params: Record<string, unknown> = {};
    for (const [key, value] of Object.entries(query)) {
        const parsed = key === "kind" ? undefined : parseValue(spec[key]!, value);
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

/** What names a comparison: the echoed query, or ids known before fetching. */
export type DisplayKeyQuery =
    | Pick<Extract<ComparisonQuery, { kind: "step_runs" }>, "kind" | "workflow_id" | "step_label">
    | Pick<Extract<ComparisonQuery, { kind: "output_runs" }>, "kind" | "workflow_id">
    | Pick<Extract<ComparisonQuery, { kind: "tool_runs" }>, "kind" | "tool_id">;

/** Local-storage key for display preferences; the step tab and the page share it, and tool versions share one. */
export function displayStorageKey(query: DisplayKeyQuery): string {
    switch (query.kind) {
        case "step_runs":
            return `step_runs:${query.workflow_id}:${query.step_label}`;
        case "output_runs":
            return `output_runs:${query.workflow_id}`;
        case "tool_runs":
            return `tool_runs:${versionlessToolId(query.tool_id)}`;
        default: {
            // A new kind fails type-check here.
            const unknownKind: never = query;
            throw new Error(`Unknown comparison kind ${JSON.stringify(unknownKind)}`);
        }
    }
}

const JOB_STATE_OPTIONS: readonly JobState[] = [
    "new",
    "queued",
    "running",
    "ok",
    "error",
    "paused",
    "skipped",
    "deleted",
];
const INVOCATION_STATE_OPTIONS: readonly InvocationState[] = [
    "new",
    "ready",
    "scheduled",
    "completed",
    "failed",
    "cancelled",
];

/** States offered by the state filter: job states for steps and tools, invocation states for workflows. */
export const STATE_OPTIONS: Record<ComparisonKind, readonly string[]> = {
    step_runs: JOB_STATE_OPTIONS,
    output_runs: INVOCATION_STATE_OPTIONS,
    tool_runs: JOB_STATE_OPTIONS,
};
