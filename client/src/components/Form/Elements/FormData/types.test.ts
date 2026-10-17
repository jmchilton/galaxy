import { describe, expect, it } from "vitest";

import { type DataOption, mergeDataOptions } from "./types";

function option(id: string, extra: Partial<DataOption> = {}): DataOption {
    return { id, name: id, src: "hdca", keep: false, batch: false, tags: [], ...extra };
}

describe("mergeDataOptions", () => {
    const listed = option("listed");
    const nested = option("nested");
    const nestedMapped = option("nested", { map_over_type: "list" });

    it("keeps both entries of a collection arriving on the same page", () => {
        expect(mergeDataOptions([listed], [nested, nestedMapped])).toEqual([listed, nested, nestedMapped]);
    });

    it("keeps a map-over entry arriving after its direct entry", () => {
        expect(mergeDataOptions([listed, nested], [nestedMapped])).toEqual([listed, nested, nestedMapped]);
    });

    it("drops options already listed", () => {
        expect(mergeDataOptions([listed, nested, nestedMapped], [nestedMapped, option("new")])).toEqual([
            listed,
            nested,
            nestedMapped,
            option("new"),
        ]);
    });

    it("tells datasets and collections with the same id apart", () => {
        const dataset = option("same", { src: "hda" });
        expect(mergeDataOptions([dataset], [option("same")])).toEqual([dataset, option("same")]);
    });
});
