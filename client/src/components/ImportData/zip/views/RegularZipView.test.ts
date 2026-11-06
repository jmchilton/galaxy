import { currentPagerPage, getLocalVue, goToPage } from "@tests/vitest/helpers";
import { mount } from "@vue/test-utils";
import { describe, expect, it, vi } from "vitest";
import { defineComponent, h, type PropType } from "vue";

import type { ImportableFile } from "@/composables/zipExplorer";

import RegularZipView from "./RegularZipView.vue";

const FILES = Array.from(
    { length: 30 },
    (_, index) => ({ name: `file-${index + 1}`, path: `file-${index + 1}`, size: 1, type: "file" }) as ImportableFile,
);

vi.mock("@/composables/zipExplorer", async (importOriginal) => ({
    ...(await importOriginal<Record<string, unknown>>()),
    getImportableFiles: () => FILES,
}));

const SELECTORS = {
    CARD: ".summary-card-stub",
};

const SummaryCardStub = defineComponent({
    props: { file: { type: Object as PropType<ImportableFile>, required: true } },
    setup(props) {
        return () => h("div", { class: "summary-card-stub", "data-path": props.file.path });
    },
});

describe("RegularZipView", () => {
    it("pages through the files in the archive", async () => {
        const localVue = getLocalVue();
        const wrapper = mount(RegularZipView as object, {
            props: { explorer: {} },
            global: { ...localVue, stubs: { ...localVue.stubs, ZipFileEntrySummaryCard: SummaryCardStub } },
        });

        expect(wrapper.findAll(SELECTORS.CARD)).toHaveLength(24);

        await goToPage(wrapper, 2);

        expect(currentPagerPage(wrapper)).toBe("2");
        expect(wrapper.findAll(SELECTORS.CARD).map((card) => card.attributes("data-path"))).toEqual(
            FILES.slice(24).map((file) => file.path),
        );
    });
});
