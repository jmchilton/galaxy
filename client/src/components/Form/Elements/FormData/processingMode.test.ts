import { describe, expect, it } from "vitest";

import { hasHelp } from "@/components/Help/terms";

import { getProcessingMode, PROCESSING_HELP_TERMS } from "./processingMode";
import type { DataOption } from "./types";
import { VARIANTS } from "./variants";

function option(id: string, src: string, extra: Partial<DataOption> = {}): DataOption {
    return { id, src, name: id, keep: false, batch: false, tags: [], ...extra };
}

const flatList = option("hdca1", "hdca", { collection_type: "list" });

/** Whether the hint for a collection input accepting `collectionTypes` suggests nesting for `selected` */
function canNest(collectionTypes: string[], selected: DataOption[] = [flatList]) {
    const mode = getProcessingMode(VARIANTS["data_collection"]![0]!, "data_collection", selected, collectionTypes);
    return mode?.kind === "bulk" && mode.canNest;
}

describe("getProcessingMode", () => {
    it("only suggests nesting when a nested collection would be mapped over", () => {
        expect(canNest(["list"])).toBe(true);
        expect(canNest(["list:paired"])).toBe(true);
        expect(canNest(["paired"])).toBe(false);
        // untyped collection inputs accept any collection directly, so nothing is mapped over
        expect(canNest([])).toBe(false);
        // a nested list matches `list:list` directly
        expect(canNest(["list", "list:list"])).toBe(false);
    });

    it("judges nesting by the selected collection's type", () => {
        const pair = option("hdcaP", "hdca", { collection_type: "paired" });
        const nestedList = option("hdcaLL", "hdca", { collection_type: "list:list" });
        // nesting cannot split a pair, even when the input also accepts lists
        expect(canNest(["list", "paired"], [pair])).toBe(false);
        // a nested list:list maps over the list:list type
        expect(canNest(["list", "list:list"], [nestedList])).toBe(true);
        // before anything is selected, only suggest nesting when no accepted list type would match it directly
        expect(canNest(["list", "list:list"], [])).toBe(false);
        expect(canNest(["list", "paired"], [])).toBe(true);
    });

    it("links to help terms that exist", () => {
        for (const uri of Object.values(PROCESSING_HELP_TERMS)) {
            expect(hasHelp(uri)).toBe(true);
        }
    });
});
