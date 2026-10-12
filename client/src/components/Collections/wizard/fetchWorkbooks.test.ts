import { describe, expect, it } from "vitest";

import { columnTitleToTargetType, forBuilder } from "./fetchWorkbooks";
import SPECIFICATIONS from "./rule_target_column_specification.yml";
import type { ColumnMappingType, ParsedFetchWorkbook } from "./types";

describe("forBuilder", () => {
    it("maps dataset workbook rows and column positions into the rule builder", () => {
        const parsedWorkbook: ParsedFetchWorkbook = {
            rows: [
                { list_identifiers: "Row1", url: "http://example.com/1", dbkey: "db1" },
                { list_identifiers: "Row2", url: "http://example.com/2", dbkey: "db2" },
            ],
            columns: [
                { type: "list_identifiers", title: "Name", type_index: 0 },
                { type: "url", title: "URI", type_index: 0 },
                { type: "dbkey", title: "Genome", type_index: 0 },
            ],
            workbook_type: "datasets",
            parse_log: [],
        };

        const result = forBuilder(parsedWorkbook);

        expect(result.initialElements).toEqual([
            ["Row1", "http://example.com/1", "db1"],
            ["Row2", "http://example.com/2", "db2"],
        ]);
        expect(result.rulesCreatingWhat).toBe("datasets");
        expect(result.initialMapping).toEqual([
            { type: "list_identifiers", columns: [0] },
            { type: "url", columns: [1] },
            { type: "dbkey", columns: [2] },
        ]);
    });
});

interface SpecificationTest {
    doc: string;
    column_header: string;
    maps_to: ColumnMappingType | null;
}

describe("column name to rule builder mapping targets", () => {
    it.each<SpecificationTest>(SPECIFICATIONS)("$doc", ({ column_header, maps_to }) => {
        const columnType = columnTitleToTargetType(column_header);

        if (maps_to === null) {
            expect(columnType).toBeUndefined();
        } else {
            expect(columnType).toBe(maps_to);
        }
    });
});
