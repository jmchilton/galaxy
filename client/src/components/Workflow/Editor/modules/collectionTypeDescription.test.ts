import { describe, expect, it } from "vitest";

import { CollectionTypeDescription } from "./collectionTypeDescription";

const ct = (collectionType: string) => new CollectionTypeDescription(collectionType);

describe("canMapOver over paired_or_unpaired inputs", () => {
    it("maps anything but paired over paired_or_unpaired", () => {
        expect(ct("list").canMapOver(ct("paired_or_unpaired"))).toBe(true);
        expect(ct("list:paired").canMapOver(ct("paired_or_unpaired"))).toBe(true);
        expect(ct("list:list").canMapOver(ct("paired_or_unpaired"))).toBe(true);
        expect(ct("paired").canMapOver(ct("paired_or_unpaired"))).toBe(false);
        expect(ct("paired_or_unpaired").canMapOver(ct("paired_or_unpaired"))).toBe(false);
    });
});

describe("canMapOver over compound :paired_or_unpaired inputs", () => {
    it("maps over with a remaining outer rank", () => {
        expect(ct("list:list").canMapOver(ct("list:paired_or_unpaired"))).toBe(true);
        expect(ct("list:list:paired").canMapOver(ct("list:paired_or_unpaired"))).toBe(true);
        expect(ct("list:list:list").canMapOver(ct("list:paired_or_unpaired"))).toBe(true);
    });

    it("does not map over a paired inner collection without a remaining outer rank", () => {
        expect(ct("list:paired").canMapOver(ct("list:paired_or_unpaired"))).toBe(false);
        expect(ct("paired:paired").canMapOver(ct("list:paired_or_unpaired"))).toBe(false);
    });

    it("aligns higher ranks on a rank boundary", () => {
        expect(ct("paired_or_unpaired").canMapOver(ct("paired:paired_or_unpaired"))).toBe(false);
        expect(ct("list:paired_or_unpaired").canMapOver(ct("paired:paired_or_unpaired"))).toBe(false);
        expect(ct("list:paired:paired").canMapOver(ct("paired:paired_or_unpaired"))).toBe(true);
    });

    it("does not map over without a remaining outer rank", () => {
        expect(ct("paired").canMapOver(ct("list:paired_or_unpaired"))).toBe(false);
        expect(ct("paired_or_unpaired").canMapOver(ct("list:paired_or_unpaired"))).toBe(false);
        expect(ct("list").canMapOver(ct("list:paired_or_unpaired"))).toBe(false);
        expect(ct("list").canMapOver(ct("list:list:paired_or_unpaired"))).toBe(false);
        expect(ct("list:list").canMapOver(ct("list:list:paired_or_unpaired"))).toBe(false);
    });

    it("does not map over itself", () => {
        expect(ct("list:paired_or_unpaired").canMapOver(ct("list:paired_or_unpaired"))).toBe(false);
    });
});

describe("append over sample_sheet", () => {
    it("keeps the sample_sheet outer level when the result is a valid sample_sheet type", () => {
        expect(ct("sample_sheet").append(ct("paired")).collectionType).toBe("sample_sheet:paired");
        expect(ct("sample_sheet").append(ct("record")).collectionType).toBe("sample_sheet:record");
        expect(ct("sample_sheet").append(ct("paired_or_unpaired")).collectionType).toBe(
            "sample_sheet:paired_or_unpaired",
        );
    });

    it("demotes the sample_sheet outer level to list when the result is not a valid sample_sheet type", () => {
        expect(ct("sample_sheet").append(ct("list")).collectionType).toBe("list:list");
        expect(ct("sample_sheet").append(ct("list:paired")).collectionType).toBe("list:list:paired");
        expect(ct("sample_sheet:paired").append(ct("list")).collectionType).toBe("list:paired:list");
        expect(ct("sample_sheet:paired").append(ct("paired")).collectionType).toBe("list:paired:paired");
    });
});
