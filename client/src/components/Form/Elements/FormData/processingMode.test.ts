import { describe, expect, it } from "vitest";

import { hasHelp } from "@/components/Help/terms";

import { getProcessingMode, PROCESSING_HELP_TERMS } from "./processingMode";
import type { DataOption } from "./types";
import { VARIANTS } from "./variants";

function option(id: string, src: string, extra: Partial<DataOption> = {}): DataOption {
    return { id, src, name: id, keep: false, batch: false, tags: [], ...extra };
}

const flatList = option("hdca1", "hdca", { collection_type: "list" });

function variant(key: string, index: number) {
    return VARIANTS[key]![index]!;
}

describe("getProcessingMode", () => {
    it("only suggests nesting when a nested collection would be mapped over", () => {
        function canNest(collectionTypes: string[]) {
            const mode = getProcessingMode(
                variant("data_collection", 0),
                "data_collection",
                [flatList],
                collectionTypes,
            );
            return mode?.kind === "bulk" && mode.canNest;
        }
        expect(canNest(["list"])).toBe(true);
        expect(canNest(["list:paired"])).toBe(true);
        expect(canNest(["paired"])).toBe(false);
        // untyped collection inputs accept any collection directly, so nothing is mapped over
        expect(canNest([])).toBe(false);
        // a nested list matches `list:list` directly
        expect(canNest(["list", "list:list"])).toBe(false);
    });

    it("links to help terms that exist", () => {
        for (const uri of Object.values(PROCESSING_HELP_TERMS)) {
            expect(hasHelp(uri)).toBe(true);
        }
    });
});
