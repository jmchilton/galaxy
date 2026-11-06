import { currentPagerPage, getLocalVue, goToPage, pagerPages } from "@tests/vitest/helpers";
import { mount } from "@vue/test-utils";
import { describe, expect, it } from "vitest";

import { FILE_CARD_SELECTOR, FileCardStub, makeFiles } from "./testHelpers/zipFixtures";

import ZipImportSummary from "./ZipImportSummary.vue";

function mountSummary(fileCount: number) {
    const localVue = getLocalVue();
    return mount(ZipImportSummary as object, {
        props: { filesToImport: makeFiles("file", fileCount) },
        global: { ...localVue, stubs: { ...localVue.stubs, ZipFileEntrySummaryCard: FileCardStub } },
    });
}

describe("ZipImportSummary", () => {
    it("pages through the files to import", async () => {
        const wrapper = mountSummary(30);

        expect(wrapper.findAll(FILE_CARD_SELECTOR)).toHaveLength(24);
        expect(currentPagerPage(wrapper)).toBe("1");

        await goToPage(wrapper, 2);

        expect(currentPagerPage(wrapper)).toBe("2");
        expect(wrapper.findAll(FILE_CARD_SELECTOR).map((card) => card.attributes("data-path"))).toEqual(
            makeFiles("file", 30)
                .slice(24)
                .map((file) => file.path),
        );
    });

    it("shows no pager when every file fits on one page", () => {
        const wrapper = mountSummary(24);

        expect(pagerPages(wrapper)).toEqual([]);
    });
});
