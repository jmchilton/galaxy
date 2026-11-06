import { currentPagerPage, getLocalVue, goToPage, pagerPages } from "@tests/vitest/helpers";
import { mount } from "@vue/test-utils";
import { describe, expect, it } from "vitest";

import { FILE_CARD_SELECTOR, FileCardStub, makeFiles } from "./testHelpers/zipFixtures";

import ZipFileSelector from "./ZipFileSelector.vue";
import DelayedInput from "@/components/Common/DelayedInput.vue";

const ALPHA_FILES = makeFiles("alpha", 30);
const BETA_FILES = makeFiles("beta", 30);

function mountSelector() {
    const localVue = getLocalVue();
    return mount(ZipFileSelector as object, {
        props: {
            zipSource: "https://example.org/archive.zip",
            zipContents: { workflows: [], files: [...ALPHA_FILES, ...BETA_FILES] },
            selectedItems: [],
        },
        global: {
            ...localVue,
            stubs: { ...localVue.stubs, ListHeader: true, ZipFileEntryCard: FileCardStub },
        },
    });
}

function shownPaths(wrapper: ReturnType<typeof mountSelector>) {
    return wrapper.findAll(FILE_CARD_SELECTOR).map((card) => card.attributes("data-path"));
}

describe("ZipFileSelector", () => {
    it("pages through the files in the archive", async () => {
        const wrapper = mountSelector();

        expect(pagerPages(wrapper)).toEqual(["1", "2", "3"]);
        expect(shownPaths(wrapper)).toEqual(ALPHA_FILES.slice(0, 24).map((file) => file.path));

        await goToPage(wrapper, 3);

        expect(currentPagerPage(wrapper)).toBe("3");
        expect(shownPaths(wrapper)).toEqual(BETA_FILES.slice(18).map((file) => file.path));
    });

    it("goes back to the first page when the search changes", async () => {
        const wrapper = mountSelector();
        await goToPage(wrapper, 3);

        wrapper.findComponent(DelayedInput).vm.$emit("change", "beta");
        await wrapper.vm.$nextTick();

        expect(pagerPages(wrapper)).toEqual(["1", "2"]);
        expect(currentPagerPage(wrapper)).toBe("1");
        expect(shownPaths(wrapper)).toEqual(BETA_FILES.slice(0, 24).map((file) => file.path));
    });
});
