import { currentPagerPage, getLocalVue, goToPage } from "@tests/vitest/helpers";
import { mount } from "@vue/test-utils";
import { describe, expect, it } from "vitest";
import { defineComponent, h, type PropType } from "vue";

import type { ImportableFile, IZipExplorer } from "@/composables/zipExplorer";

import GalaxyZipView from "./GalaxyZipView.vue";

const FILE_PATHS = Array.from({ length: 30 }, (_, index) => `file-${String(index + 1).padStart(2, "0")}`);

const EXPLORER = {
    entries: new Map(FILE_PATHS.map((path) => [path, { type: "File", path }])),
    getFileEntryMetadata: ({ path }: { path: string }) => ({ name: path, path, size: 1 }),
} as unknown as IZipExplorer;

const CARD_SELECTOR = ".entry-card-stub";

const EntryCardStub = defineComponent({
    props: { file: { type: Object as PropType<ImportableFile>, required: true } },
    setup(props) {
        return () => h("div", { class: "entry-card-stub", "data-path": props.file.path });
    },
});

describe("GalaxyZipView", () => {
    it("pages through the files in the export archive", async () => {
        const localVue = getLocalVue();
        const wrapper = mount(GalaxyZipView as object, {
            props: { explorer: EXPLORER },
            global: { ...localVue, stubs: { ...localVue.stubs, ZipFileEntryCard: EntryCardStub } },
        });

        expect(wrapper.findAll(CARD_SELECTOR)).toHaveLength(24);

        await goToPage(wrapper, 2);

        expect(currentPagerPage(wrapper)).toBe("2");
        expect(wrapper.findAll(CARD_SELECTOR).map((card) => card.attributes("data-path"))).toEqual(
            FILE_PATHS.slice(24),
        );
    });
});
