import { shallowMount } from "@vue/test-utils";
import { describe, expect, it } from "vitest";

import { STEP_RUNS_TABLE } from "./test-utils";

import ComparisonColumnCell from "./ComparisonColumnCell.vue";

const INPUT = STEP_RUNS_TABLE.columns.find((column) => column.key === "input:input1")!;
const ROW = STEP_RUNS_TABLE.rows[1]!;

function mountCell(changed?: boolean) {
    return shallowMount(ComparisonColumnCell as object, {
        props: { row: ROW, column: INPUT, display: "link", changed, requestedMetadata: ["columns"], loading: true },
    });
}

describe("ComparisonColumnCell", () => {
    it("renders the row's cell of the column with the column's role", () => {
        const cell = mountCell().findComponent({ name: "ComparisonCell" });
        expect(cell.props()).toMatchObject({
            cell: ROW.cells["input:input1"],
            row: ROW,
            display: "link",
            role: "input",
            requestedMetadata: ["columns"],
            loading: true,
        });
    });

    it("titles a changed cell", () => {
        expect(mountCell(true).attributes("title")).toBe("Differs from the run you are viewing");
        expect(mountCell().attributes("title")).toBeUndefined();
    });
});
