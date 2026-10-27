import type { ComparisonCell, ComparisonColumn, ComparisonRow } from "@/api/comparisons";

import { type CellDisplay, metadataKeyOf, type MetaField } from "./comparisonUtils";

/** Whether two cells show the same thing; `uncompared` when only item identity would tell them apart. */
export type CellComparison = "same" | "differs" | "uncompared";

const UNCOMPARED = Symbol("uncompared");

/** JSON with object keys sorted, so equal values serialize equally. */
export function stableStringify(value: unknown): string {
    return JSON.stringify(value, (_key, item) =>
        item && typeof item === "object" && !Array.isArray(item)
            ? Object.fromEntries(Object.entries(item).sort(([a], [b]) => (a < b ? -1 : a > b ? 1 : 0)))
            : item,
    );
}

/** What a cell shows under `display`, as a string to compare. */
function cellIdentity(
    cell: ComparisonCell | undefined,
    column: ComparisonColumn,
    display: CellDisplay,
): string | typeof UNCOMPARED {
    if (!cell) {
        return "none";
    }
    if (cell.type === "missing") {
        return `missing:${cell.reason}`;
    }
    if (cell.type === "value") {
        return `value:${stableStringify(cell.value)}`;
    }
    const element = metadataKeyOf(display);
    if (element) {
        return cell.type === "dataset"
            ? `meta:${stableStringify(cell.metadata[element] ?? null)}`
            : `collection:${cell.collection_type}:${cell.element_count}`;
    }
    // Every run makes new outputs, so their ids always differ.
    return column.role === "output" ? UNCOMPARED : `${cell.type}:${cell.id}`;
}

export function compareCells(
    a: ComparisonCell | undefined,
    b: ComparisonCell | undefined,
    column: ComparisonColumn,
    display: CellDisplay,
): CellComparison {
    const left = cellIdentity(a, column, display);
    const right = cellIdentity(b, column, display);
    if (left === UNCOMPARED && right === UNCOMPARED) {
        return "uncompared";
    }
    return left === right ? "same" : "differs";
}

function metaIdentity(field: MetaField, row: ComparisonRow): unknown {
    switch (field) {
        case "version":
            return row.version;
        case "tool_version":
            return row.tool_version;
        case "state":
            return row.state;
        case "reused":
            return row.reused;
        case "history":
            return row.history.id;
        default:
            return UNCOMPARED;
    }
}

export function compareMeta(field: MetaField, a: ComparisonRow, b: ComparisonRow): CellComparison {
    const left = metaIdentity(field, a);
    if (left === UNCOMPARED) {
        return "uncompared";
    }
    return (left ?? null) === (metaIdentity(field, b) ?? null) ? "same" : "differs";
}

/** Column keys of each row's cells that differ from the current run's row; empty unless that row is on the page. */
export function changedCells(
    rows: ComparisonRow[],
    columns: ComparisonColumn[],
    displayOf: (column: ComparisonColumn) => CellDisplay,
    currentRunId: string | undefined,
): Map<string, Set<string>> {
    const changed = new Map<string, Set<string>>();
    const current = rows.find((row) => row.run.id === currentRunId);
    if (!current) {
        return changed;
    }
    for (const row of rows) {
        if (row === current) {
            continue;
        }
        const keys = columns
            .filter((column) => {
                const display = displayOf(column);
                return compareCells(current.cells[column.key], row.cells[column.key], column, display) === "differs";
            })
            .map((column) => column.key);
        if (keys.length) {
            changed.set(row.run.id, new Set(keys));
        }
    }
    return changed;
}
