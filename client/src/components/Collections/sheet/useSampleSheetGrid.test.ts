import { mount } from "@vue/test-utils";
import { AllCommunityModule, type GridApi, type GridReadyEvent, ModuleRegistry } from "ag-grid-community";
import { AgGridVue } from "ag-grid-vue3";
import { describe, expect, it, vi } from "vitest";

import type { SampleSheetColumnDefinition } from "@/api";

import {
    MODEL_OBJECT,
    modelObjectIdentifierColumn,
    type ModelObjectRow,
    parseSampleSheetValue,
} from "./useSampleSheetGrid";

function column(type: SampleSheetColumnDefinition["type"], extra: Partial<SampleSheetColumnDefinition> = {}) {
    return { name: "column", type, optional: false, ...extra } as SampleSheetColumnDefinition;
}

describe("parseSampleSheetValue", () => {
    it.each([
        ["int", "3", 3],
        ["int", 3, 3],
        ["float", "1.5", 1.5],
        ["float", "1e3", 1000],
        ["boolean", "TRUE", true],
        ["boolean", false, false],
        ["string", "treated 1", "treated 1"],
        ["element_identifier", "sample 1", "sample 1"],
    ] as const)("parses a %s column's %j as %j", (type, input, expected) => {
        expect(parseSampleSheetValue(input, column(type))).toEqual({ valid: true, value: expected });
    });

    it.each([
        ["int", "1.5"],
        ["int", ""],
        ["int", null],
        ["float", "1,5"],
        ["float", "1abc"],
        ["boolean", "yes"],
        ["string", "a/b"],
        ["element_identifier", "sample.1"],
    ] as const)("rejects a %s column's %j", (type, input) => {
        expect(parseSampleSheetValue(input, column(type))).toEqual({ valid: false });
    });

    it("clears optional typed columns to null", () => {
        expect(parseSampleSheetValue("", column("float", { optional: true }))).toEqual({ valid: true, value: null });
    });

    it("keeps an optional string column's empty value", () => {
        expect(parseSampleSheetValue("", column("string", { optional: true }))).toEqual({ valid: true, value: "" });
    });

    it("compares restrictions as text", () => {
        const restricted = column("int", { restrictions: [1, 2] });
        expect(parseSampleSheetValue("2", restricted)).toEqual({ valid: true, value: 2 });
        expect(parseSampleSheetValue("3", restricted)).toEqual({ valid: false });
    });
});

describe("model object rows in the real ag-grid wrapper", () => {
    ModuleRegistry.registerModules([AllCommunityModule]);
    const element = { element_identifier: "sample1", object: { id: "1", model_class: "HistoryDatasetAssociation" } };

    it("keeps the model object through grid rows and edit write-back", async () => {
        let api: GridApi | undefined;
        const wrapper = mount({ ...AgGridVue, compatConfig: { MODE: 3 } } as any, {
            props: {
                modelValue: [{ treatment: "a", [MODEL_OBJECT]: element } as unknown as ModelObjectRow],
                columnDefs: [modelObjectIdentifierColumn("Identifier"), { field: "treatment", editable: true }],
                onGridReady: (params: GridReadyEvent) => (api = params.api),
                "onUpdate:modelValue": () => {},
            },
            attachTo: document.body,
        });
        await vi.waitFor(() => expect(api).toBeDefined());
        const node = api!.getDisplayedRowAtIndex(0)!;
        expect(api!.getCellValue({ rowNode: node, colKey: "model-object-identifier" })).toBe("sample1");
        node.setDataValue("treatment", "b");
        await vi.waitFor(() => expect(wrapper.emitted("update:modelValue")).toBeTruthy());
        const [rows] = wrapper.emitted("update:modelValue")!.at(-1) as [ModelObjectRow[]];
        expect(rows[0]![MODEL_OBJECT]).toMatchObject({ element_identifier: "sample1" });
        wrapper.unmount();
    });
});
