import { currentPagerPage, getLocalVue, goToPage } from "@tests/vitest/helpers";
import { mount } from "@vue/test-utils";
import { describe, expect, it } from "vitest";

import { FILE_CARD_SELECTOR, FileCardStub, makeExplorer, makeFiles } from "../testHelpers/zipFixtures";

import GalaxyZipView from "./GalaxyZipView.vue";
import RegularZipView from "./RegularZipView.vue";

const FILES = makeFiles("file", 30);

describe.each([
    { name: "GalaxyZipView", view: GalaxyZipView, card: "ZipFileEntryCard" },
    { name: "RegularZipView", view: RegularZipView, card: "ZipFileEntrySummaryCard" },
])("$name", ({ view, card }) => {
    it("pages through the files in the archive", async () => {
        const localVue = getLocalVue();
        const wrapper = mount(view as object, {
            props: { explorer: makeExplorer(FILES) },
            global: { ...localVue, stubs: { ...localVue.stubs, [card]: FileCardStub } },
        });

        expect(wrapper.findAll(FILE_CARD_SELECTOR)).toHaveLength(24);

        await goToPage(wrapper, 2);

        expect(currentPagerPage(wrapper)).toBe("2");
        expect(wrapper.findAll(FILE_CARD_SELECTOR).map((card) => card.attributes("data-path"))).toEqual(
            FILES.slice(24).map((file) => file.path),
        );
    });
});
