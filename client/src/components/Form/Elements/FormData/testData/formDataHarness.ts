/** Mounting helpers and fixtures shared by the FormData component specs */
import { createTestingPinia } from "@pinia/testing";
import { getLocalVue } from "@tests/vitest/helpers";
import { mount } from "@vue/test-utils";
import { vi } from "vitest";

import { testDatatypesMapper } from "@/components/Datatypes/test_fixtures";
import { useDatatypesMapperStore } from "@/stores/datatypesMapperStore";
import { useEventStore } from "@/stores/eventStore";

import MountTarget from "../FormData.vue";

const localVue = getLocalVue();

export let eventStore: ReturnType<typeof useEventStore>;

export function createTarget(propsData: Record<string, any>) {
    const pinia = createTestingPinia({ createSpy: vi.fn, stubActions: false });
    eventStore = useEventStore();
    const datatypesStore = useDatatypesMapperStore();
    datatypesStore.datatypesMapper = testDatatypesMapper;
    return mount(MountTarget as any, {
        global: localVue,
        props: propsData,
        pinia,
        stubs: {
            FontAwesomeIcon: true,
        },
    });
}

export const defaultOptions = {
    dce: [
        { id: "dce1", name: "dceName1", src: "dce", is_dataset: true },
        { id: "dce2", name: "dceName2", src: "dce" },
        { id: "dce3", name: "dceName3", src: "dce", map_over_type: "mapOverType" },
        { id: "dce4", name: "dceName4", src: "dce", is_dataset: true },
    ],
    hda: [
        { id: "hda1", hid: 1, name: "hdaName1", src: "hda", tags: ["tag1"] },
        { id: "hda2", hid: 2, name: "hdaName2", src: "hda", tags: ["tag1", "tag2"] },
        { id: "hda3", hid: 3, name: "hdaName3", src: "hda", tags: ["tag2", "tag3"] },
        { id: "hda4", hid: 4, name: "hdaName4", src: "hda" },
    ],
    hdca: [
        { id: "hdca5", hid: 5, name: "hdcaName5", src: "hdca" },
        { id: "hdca6", hid: 6, name: "hdcaName6", src: "hdca" },
    ],
};

// inputs accepting both X and list:X list a list:list collection twice: directly and mapped over
export const nestedListProps = {
    type: "data_collection",
    collectionTypes: ["list", "list:list"],
    options: {
        hdca: [
            { id: "hdcaLL", hid: 9, name: "nested", src: "hdca", collection_type: "list:list" },
            { id: "hdcaLL", hid: 9, name: "nested", src: "hdca", collection_type: "list:list", map_over_type: "list" },
            { id: "hdcaL", hid: 8, name: "flat", src: "hdca", collection_type: "list" },
        ],
    },
};

export const SELECT_OPTIONS = ".multiselect__element";
export const SELECTED_VALUE = ".multiselect__option--selected";

// vue-multiselect only renders its option list (and thus SELECT_OPTIONS /
// SELECTED_VALUE) while its dropdown is open, so tests need to open it
// before reading those. Selecting a new value in single-select mode closes
// the dropdown again, so callers re-open as needed between assertions.
export async function openMultiselect(wrapper: ReturnType<typeof createTarget>) {
    if (!wrapper.find(".multiselect__content-wrapper").exists()) {
        await wrapper.find(".multiselect__select").trigger("mousedown");
    }
}
