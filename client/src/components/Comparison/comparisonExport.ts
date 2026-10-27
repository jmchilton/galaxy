import type {
    ComparisonCell,
    ComparisonColumn,
    ComparisonQuery,
    ComparisonRow,
    ComparisonTable,
} from "@/api/comparisons";
import { versionlessToolId } from "@/utils/tool-version";

import {
    type CellDisplay,
    isScalar,
    META_FIELD_SPECS,
    metadataKeyOf,
    missingText,
    visibleFields,
} from "./comparisonUtils";

export type ExportFormat = "csv" | "tsv";

function valueText(value: unknown): string {
    return isScalar(value) ? String(value ?? "null") : JSON.stringify(value);
}

/** A cell as the table shows it under `display`, on one line. */
export function cellText(
    cell: ComparisonCell | undefined,
    row: Pick<ComparisonRow, "version" | "tool_version">,
    display: CellDisplay,
    role?: ComparisonColumn["role"],
): string {
    if (!cell) {
        return "";
    }
    if (cell.type === "missing") {
        return missingText(cell, row, role);
    }
    if (cell.type === "value") {
        return valueText(cell.value);
    }
    if (cell.type === "dataset_list") {
        return cell.items.map((item) => cellText(item, row, display)).join("; ");
    }
    const element = metadataKeyOf(display);
    if (element) {
        if (cell.type === "collection") {
            return `${cell.collection_type} · ${cell.element_count ?? "?"}`;
        }
        const value = cell.metadata[element];
        return value === undefined || value === null ? "" : valueText(value);
    }
    const name = cell.name ?? cell.id;
    return cell.hid === null || cell.hid === undefined ? name : `${cell.hid}: ${name}`;
}

export interface ExportOptions {
    /** Keys of the shown meta fields and data columns; the anchor field is always written. */
    visibleColumns: string[];
    transpose: boolean;
    displayOf: (column: ComparisonColumn) => CellDisplay;
}

/** The table's shown fields and columns as lines of text, runs as rows or, transposed, as columns. */
export function exportLines(table: ComparisonTable, options: ExportOptions): string[][] {
    const { anchor, metaFields, columns } = visibleFields(table.query.kind, table.columns, options.visibleColumns);
    const fields = [
        ...[anchor, ...metaFields].map((field) => META_FIELD_SPECS[field]),
        ...columns.map((column) => ({
            label: `${column.label} (${column.role})`,
            text: (row: ComparisonRow) => cellText(row.cells[column.key], row, options.displayOf(column), column.role),
        })),
    ];
    if (options.transpose) {
        return fields.map((field) => [field.label, ...table.rows.map(field.text)]);
    }
    return [fields.map((field) => field.label), ...table.rows.map((row) => fields.map((field) => field.text(row)))];
}

const NUMBER = /^[-+]?(\d+\.?\d*|\.\d+)([eE][-+]?\d+)?$/;

/** Prefixes `'` to text a spreadsheet would read as a formula; numbers stay numbers. */
export function spreadsheetSafe(text: string): string {
    return /^[=+\-@\t\r]/.test(text) && !NUMBER.test(text) ? `'${text}` : text;
}

function csvField(text: string): string {
    return /[",\r\n]/.test(text) ? `"${text.replace(/"/g, '""')}"` : text;
}

function tsvField(text: string): string {
    return text.replace(/\r\n|[\t\r\n]/g, " ");
}

export function toDelimited(lines: string[][], format: ExportFormat): string {
    const [field, separator] = format === "csv" ? [csvField, ","] : [tsvField, "\t"];
    return lines.map((line) => line.map((text) => field(spreadsheetSafe(text))).join(separator) + "\r\n").join("");
}

const EXPORT_MIME_TYPES: Record<ExportFormat, string> = {
    csv: "text/csv",
    tsv: "text/tab-separated-values",
};

// Without a byte order mark, Excel reads a CSV in the system code page.
const UTF8_BOM = "﻿";

export function exportBlob(lines: string[][], format: ExportFormat): Blob {
    const bom = format === "csv" ? UTF8_BOM : "";
    return new Blob([bom + toDelimited(lines, format)], { type: `${EXPORT_MIME_TYPES[format]};charset=utf-8` });
}

function comparisonName(query: ComparisonQuery): string {
    switch (query.kind) {
        case "step_runs":
            return `runs_of_${query.step_label}`;
        case "output_runs":
            return "workflow_runs";
        case "tool_runs":
            return `runs_of_${versionlessToolId(query.tool_id)}`;
        default: {
            const unknown: never = query;
            return String(unknown);
        }
    }
}

/** A file name for one page of a comparison: what it compares and which rows. */
export function exportFilename(query: ComparisonQuery, rowCount: number, format: ExportFormat): string {
    const offset = query.offset ?? 0;
    const name = comparisonName(query).replace(/[^A-Za-z0-9._-]+/g, "_");
    return `${name}_${offset + 1}-${offset + rowCount}.${format}`;
}
