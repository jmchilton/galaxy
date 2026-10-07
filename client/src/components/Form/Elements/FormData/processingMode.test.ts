import { describe, expect, it } from "vitest";

import { hasHelp } from "@/components/Help/terms";

import { getProcessingMode, mapOverUnit, PROCESSING_HELP_TERMS } from "./processingMode";
import type { DataOption } from "./types";
import { VARIANTS } from "./variants";

function option(id: string, src: string, extra: Partial<DataOption> = {}): DataOption {
    return { id, src, name: id, keep: false, batch: false, tags: [], ...extra };
}

const hda = option("hda1", "hda");
const flatList = option("hdca1", "hdca", { collection_type: "list" });

function variant(key: string, index: number) {
    return VARIANTS[key]![index]!;
}

describe("getProcessingMode", () => {
    it("says nothing for a single dataset in a single dataset input", () => {
        expect(getProcessingMode(variant("data", 0), "data", [hda])).toBeNull();
        expect(getProcessingMode(null, "data", [hda])).toBeNull();
    });

    it("runs one job per dataset for multiple datasets in a single dataset input", () => {
        expect(getProcessingMode(variant("data", 1), "data", [hda, option("hda2", "hda")])).toEqual({
            kind: "batch",
            source: "datasets",
            hasSelection: true,
            perItem: true,
        });
    });

    it("maps a collection over a single dataset input one dataset at a time", () => {
        expect(getProcessingMode(variant("data", 2), "data", [flatList])).toEqual({
            kind: "batch",
            source: "collection",
            hasSelection: true,
            perItem: false,
            collectionType: "list",
        });
    });

    it("processes multiple datasets or flat lists together in a multiple input", () => {
        expect(getProcessingMode(variant("data_multiple", 0), "data", [hda])).toEqual({
            kind: "bulk",
            source: "datasets",
            hasSelection: true,
            plural: false,
            canNest: true,
        });
        const otherList = option("hdca6", "hdca", { collection_type: "list" });
        expect(getProcessingMode(variant("data_multiple", 1), "data", [flatList, otherList])).toEqual({
            kind: "bulk",
            source: "collection",
            hasSelection: true,
            plural: true,
            canNest: true,
        });
    });

    it("maps a nested list over a multiple input one inner list at a time", () => {
        const nested = option("hdca2", "hdca", { map_over_type: "list", collection_type: "list:list" });
        expect(getProcessingMode(variant("data_multiple", 1), "data", [nested])).toEqual({
            kind: "batch",
            source: "collection",
            hasSelection: true,
            perItem: false,
            mapOverType: "list",
            collectionType: "list:list",
        });
    });

    it("runs one job per selected collection when several are batched", () => {
        // the server only splits a collection when it is the sole batch value
        const nested = option("hdca2", "hdca", { map_over_type: "list", collection_type: "list:list" });
        expect(getProcessingMode(variant("data_multiple", 1), "data", [nested, flatList])).toEqual({
            kind: "batch",
            source: "collection",
            hasSelection: true,
            perItem: true,
        });
    });

    it("processes a directly matching collection as a whole", () => {
        const pair = option("hdca3", "hdca", { collection_type: "paired" });
        expect(getProcessingMode(variant("data_collection", 0), "data_collection", [pair], ["paired"])).toEqual({
            kind: "bulk",
            source: "collection",
            hasSelection: true,
            plural: false,
            canNest: false,
        });
    });

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

    it("maps a list of pairs over a paired collection input", () => {
        const listPaired = option("hdca4", "hdca", { map_over_type: "paired" });
        expect(getProcessingMode(variant("data_collection", 0), "data_collection", [listPaired], ["paired"])).toEqual({
            kind: "batch",
            source: "collection",
            hasSelection: true,
            perItem: false,
            mapOverType: "paired",
        });
    });

    it("treats a paired_or_unpaired map over of a plain list as one job per dataset", () => {
        const list = option("hdca5", "hdca", { map_over_type: "single_datasets", collection_type: "list" });
        expect(
            getProcessingMode(variant("data_collection", 0), "data_collection", [list], ["paired_or_unpaired"]),
        ).toEqual({ kind: "batch", source: "collection", hasSelection: true, perItem: false, collectionType: "list" });
    });

    it("describes the field when nothing is selected yet", () => {
        expect(getProcessingMode(variant("data_multiple", 0), "data", [])).toMatchObject({
            kind: "bulk",
            hasSelection: false,
        });
        expect(getProcessingMode(variant("data_collection", 0), "data_collection", [], ["list"])).toMatchObject({
            kind: "bulk",
            hasSelection: false,
        });
        expect(getProcessingMode(variant("data", 2), "data", [])).toMatchObject({
            kind: "batch",
            hasSelection: false,
        });
        expect(getProcessingMode(variant("data", 0), "data", [])).toBeNull();
    });

    it("links to help terms that exist", () => {
        for (const uri of Object.values(PROCESSING_HELP_TERMS)) {
            expect(hasHelp(uri)).toBe(true);
        }
    });
});

describe("mapOverUnit", () => {
    it("names what each mapped-over job receives", () => {
        expect(mapOverUnit("paired")).toBe("dataset pair");
        expect(mapOverUnit("list:paired")).toBe("list of pairs");
        expect(mapOverUnit("list:list")).toBe("nested list:list");
        // a plain list fed to a paired_or_unpaired input, or a collection fed to a dataset input
        expect(mapOverUnit("single_datasets")).toBe("dataset");
        expect(mapOverUnit(null)).toBe("dataset");
    });
});
