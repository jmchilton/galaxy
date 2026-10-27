import type {
    ComparisonCell,
    ComparisonColumn,
    ComparisonKind,
    ComparisonQuery,
    ComparisonRow,
    MissingCell,
} from "@/api/comparisons";
import { statePlaceholders } from "@/composables/useInvocationGraph";

/** How a column renders its cells: name with popover, the value itself, or one metadata element. */
export type CellDisplay = "link" | "value" | `meta:${string}`;

/** Run columns shown before the input and output columns. */
export type MetaField = "invoked" | "run" | "version" | "tool_version" | "state" | "reused" | "history";

export const META_FIELDS: Record<ComparisonKind, MetaField[]> = {
    step_runs: ["invoked", "version", "state", "reused", "history"],
    output_runs: ["invoked", "version", "state", "history"],
    tool_runs: ["run", "tool_version", "state", "reused", "history"],
};

/** The anchor field, which is always shown, then the shown run fields and data columns. */
export function visibleFields(kind: ComparisonKind, columns: ComparisonColumn[], visibleColumns: string[]) {
    const [anchor, ...optional] = META_FIELDS[kind];
    return {
        anchor: anchor!,
        metaFields: optional.filter((field) => visibleColumns.includes(field)),
        columns: columns.filter((column) => visibleColumns.includes(column.key)),
    };
}

export const META_LABELS: Record<MetaField, string> = {
    invoked: "Invoked",
    run: "Ran",
    version: "Version",
    tool_version: "Tool version",
    state: "State",
    reused: "Reused",
    history: "History",
};

export const ROLE_LABELS: Record<ComparisonColumn["role"], string> = {
    input: "in",
    output: "out",
    parameter: "param",
};

/** A state as the invocation view names it; failed_metadata's placeholder only reads after a job count. */
export function stateText(state: string): string {
    return state === "failed_metadata" ? state : (statePlaceholders[state] ?? state);
}

/** Versions are 0-based on the wire and 1-based in the UI. */
export function versionLabel(version: number | null | undefined): string {
    return Number.isFinite(version) ? `v${version! + 1}` : "";
}

/** GTable slot names are `cell(${key})`, so map arbitrary column keys to safe field keys. */
export function fieldKeys(columns: ComparisonColumn[]): Record<string, string> {
    return Object.fromEntries(columns.map((column, index) => [column.key, `c${index}`]));
}

function columnCells(column: ComparisonColumn, rows: ComparisonRow[]): ComparisonCell[] {
    return rows.map((row) => row.cells[column.key]).filter((cell): cell is ComparisonCell => Boolean(cell));
}

/** Parameters and inlined values show as values; datasets and collections as links. */
export function defaultDisplay(column: ComparisonColumn, rows: ComparisonRow[]): CellDisplay {
    if (column.role === "parameter" || columnCells(column, rows).some((cell) => cell.type === "value")) {
        return "value";
    }
    return "link";
}

export function displayFor(
    column: ComparisonColumn,
    rows: ComparisonRow[],
    columnDisplay: Record<string, CellDisplay>,
): CellDisplay {
    return columnDisplay[column.key] ?? defaultDisplay(column, rows);
}

export function metadataKeyOf(display: CellDisplay): string | undefined {
    return display.startsWith("meta:") ? display.slice(5) : undefined;
}

/** Metadata element names the server must fill for the current displays. */
export function requestedMetadata(columnDisplay: Record<string, CellDisplay>): string[] {
    const names = Object.values(columnDisplay)
        .map(metadataKeyOf)
        .filter((name): name is string => Boolean(name));
    return [...new Set(names)].sort();
}

export function displayLabel(display: CellDisplay): string {
    const key = metadataKeyOf(display);
    if (key) {
        return `metadata: ${key}`;
    }
    return display === "value" ? "value" : "name";
}

export interface DisplayOption {
    display: CellDisplay;
    label: string;
    disabled?: boolean;
}

export function displayOptions(column: ComparisonColumn, rows: ComparisonRow[]): DisplayOption[] {
    const isParameter = column.role === "parameter";
    const hasValues = isParameter || columnCells(column, rows).some((cell) => cell.type === "value");
    const options: DisplayOption[] = [
        { display: "link", label: "Name with popover", disabled: isParameter },
        { display: "value", label: "Value", disabled: !hasValues },
    ];
    if (!isParameter) {
        column.metadata_keys.forEach((key) => options.push({ display: `meta:${key}`, label: key }));
    }
    return options;
}

const MISSING_TITLES: Record<MissingCell["reason"], string> = {
    not_in_version: "This version has no input or output with this name",
    not_run_yet: "This run has not reached this step yet",
    skipped: "This step was skipped in this run",
    no_output: "This run produced nothing here",
    inaccessible: "You do not have access to this item",
};

const NOT_SUPPLIED_TITLE = "This run did not supply this input";

/** An input left empty reads "not supplied" rather than "no output". */
function notSupplied(cell: MissingCell, role?: ComparisonColumn["role"]): boolean {
    return cell.reason === "no_output" && role === "input";
}

export function missingTitle(cell: MissingCell, role?: ComparisonColumn["role"]): string {
    return notSupplied(cell, role) ? NOT_SUPPLIED_TITLE : MISSING_TITLES[cell.reason];
}

export function missingText(
    cell: MissingCell,
    row: Pick<ComparisonRow, "version" | "tool_version">,
    role?: ComparisonColumn["role"],
): string {
    if (notSupplied(cell, role)) {
        return "not supplied";
    }
    switch (cell.reason) {
        case "not_in_version":
            if (row.version !== null && row.version !== undefined) {
                return `not in ${versionLabel(row.version)}`;
            }
            return row.tool_version ? `not in ${row.tool_version}` : "not in this version";
        case "not_run_yet":
            return "not run yet";
        case "skipped":
            return "skipped";
        case "inaccessible":
            return "no access";
        case "no_output":
            return "no output";
        default: {
            // New reasons fail type-check here; at runtime show the raw reason.
            const unknown: never = cell.reason;
            return String(unknown);
        }
    }
}

export function isScalar(value: unknown): value is string | number | boolean | null | undefined {
    return value === null || value === undefined || ["string", "number", "boolean"].includes(typeof value);
}

/** Text for a value cell or metadata element; JSON pretty-printed when not scalar. */
export function formatValue(value: unknown): string {
    if (value === null || value === undefined) {
        return "null";
    }
    if (isScalar(value)) {
        return String(value);
    }
    return JSON.stringify(value, null, 2);
}

/** The job behind a row: the step's job (mode 1) or the run itself (mode 3), with ICJ batches by their first job. */
export function rowJob(
    row: ComparisonRow,
): { jobId?: string; jobCount?: number; implicitCollectionJobsId?: string } | undefined {
    const ref = row.step_job ?? (row.run.model === "WorkflowInvocation" ? undefined : row.run);
    if (!ref) {
        return undefined;
    }
    if (ref.model === "Job") {
        return { jobId: ref.id };
    }
    return { jobId: ref.representative_job_id ?? undefined, jobCount: ref.job_count, implicitCollectionJobsId: ref.id };
}

// As the invocation view counts scheduling done.
const SCHEDULING_ENDED = ["scheduled", "cancelled", "failed", "completed"];
const INPUT_STEP_TYPES = ["data_input", "data_collection_input", "parameter_input"];

/** Why a step or tool run row has no job to show; undefined when it has one. */
export function noJobReason(row: ComparisonRow): string | undefined {
    const job = rowJob(row);
    const runEnded = row.run.model === "WorkflowInvocation" && SCHEDULING_ENDED.includes(row.run.state);
    if (job?.jobCount === 0) {
        return "Mapped over an empty collection: no jobs ran.";
    }
    if (job?.jobId || row.subworkflow_invocation_id) {
        return undefined;
    }
    // Steps are "new" or "ready" until scheduled.
    if (["new", "ready"].includes(row.state)) {
        return runEnded ? "This run ended before reaching this step." : "This run has no job for this step yet.";
    }
    if (row.step_type === "pause") {
        if (row.step_action === true) {
            return "Reviewed: the run continued past this pause.";
        }
        if (row.step_action === false) {
            return "Review rejected: the run was cancelled at this pause.";
        }
        return runEnded
            ? "This pause step was not reviewed before the run ended."
            : "Waiting for review: the run is paused at this step.";
    }
    if (row.step_type && INPUT_STEP_TYPES.includes(row.step_type)) {
        return "Input steps run without a job.";
    }
    return "This step ran without a job.";
}

/** Where a row's run lives; mode 1 asks the invocation view to select the step (#24173). */
export function runLink(row: ComparisonRow, query: ComparisonQuery): string {
    const run = row.run;
    if (run.model === "WorkflowInvocation") {
        const base = `/workflows/invocations/${run.id}`;
        return query.kind === "step_runs" ? `${base}?step_label=${encodeURIComponent(query.step_label)}` : base;
    }
    if (run.model === "Job") {
        return `/jobs/${run.id}/view`;
    }
    return run.representative_job_id ? `/jobs/${run.representative_job_id}/view` : "";
}

export function historyLink(historyId: string): string {
    return `/histories/view?id=${historyId}`;
}
