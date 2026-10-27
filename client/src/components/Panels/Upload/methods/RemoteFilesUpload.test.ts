import { createTestingPinia } from "@pinia/testing";
import { getLocalVue } from "@tests/vitest/helpers";
import { mount, type Wrapper } from "@vue/test-utils";
import flushPromises from "flush-promises";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { computed, ref } from "vue";

import { browseRemoteFiles, fetchFileSources, type RemoteEntry } from "@/api/remoteFiles";

import RemoteFilesUpload from "./RemoteFilesUpload.vue";

vi.mock("@/api/remoteFiles", () => ({
    browseRemoteFiles: vi.fn(),
    fetchFileSources: vi.fn(),
}));

// defaults to a source that searches and pages on the server, like Invenio or Dataverse
const capabilities = vi.hoisted(() => ({ server: true }));

vi.mock("@/composables/fileSources", () => ({
    useFileSources: () => ({
        supportsPagination: () => capabilities.server,
        supportsSearch: () => capabilities.server,
    }),
}));

vi.mock("@/composables/upload/uploadDefaults", () => ({
    useUploadDefaults: () => ({
        effectiveExtensions: computed(() => []),
        listDbKeys: computed(() => []),
        configurationsReady: ref(true),
        createItemDefaults: () => ({ extension: "auto", dbkey: "?", spaceToTab: false, toPosixLines: false }),
    }),
}));

const localVue = getLocalVue();

const SOURCE_URI = "gxremote://source";
const FOLDER_URI = `${SOURCE_URI}/folder`;

function directory(name: string, uri: string): RemoteEntry {
    return { class: "Directory", name, uri, path: uri } as RemoteEntry;
}

function file(name: string, uri: string): RemoteEntry {
    return { class: "File", name, uri, path: uri, size: 1, ctime: "" } as RemoteEntry;
}

function listing(uri: string, offset = 0) {
    if (uri === SOURCE_URI) {
        const files = Array.from({ length: 25 }, (_, i) =>
            file(`file${offset + i}`, `${SOURCE_URI}/file${offset + i}`),
        );
        return { entries: [directory("folder", FOLDER_URI), ...files], totalMatches: 60 };
    }
    return { entries: [file("inner", `${FOLDER_URI}/inner`)], totalMatches: 1 };
}

function listingsOf(uri: string) {
    return vi.mocked(browseRemoteFiles).mock.calls.filter(([target]) => target === uri);
}

async function mountComponent() {
    const wrapper = mount(RemoteFilesUpload as object, {
        propsData: { method: { id: "remote-files" }, targetHistoryId: "history" },
        localVue,
        pinia: createTestingPinia({ createSpy: vi.fn, stubActions: false }),
        stubs: { RemoteEntryMetadata: true },
    });
    await flushPromises();
    return wrapper;
}

function rowLabels(wrapper: Wrapper<Vue>) {
    return wrapper.findAll("tbody td .d-flex > span").wrappers.map((span) => span.text());
}

async function clickRow(wrapper: Wrapper<Vue>, label: string) {
    // click the name, as a user would: BTable ignores clicks targeting the focusable row itself
    const name = wrapper.findAll("tbody td span").filter((span) => span.text() === label);
    expect(name.length).toBe(1);
    await name.at(0).trigger("click");
    await flushPromises();
}

async function search(wrapper: Wrapper<Vue>, text: string) {
    await wrapper.find(".search-bar-container input").setValue(text);
    // the search input is debounced
    await vi.advanceTimersByTimeAsync(600);
    await flushPromises();
}

async function goToPage(wrapper: Wrapper<Vue>, page: number) {
    await wrapper.find(`.pagination button[aria-label='Go to page ${page}']`).trigger("click");
    await flushPromises();
}

describe("RemoteFilesUpload", () => {
    beforeEach(() => {
        // only for the search debounce: a faked clock makes Vue 2 drop events older than their handlers
        vi.useFakeTimers({ toFake: ["setTimeout", "clearTimeout"] });
        vi.mocked(fetchFileSources).mockResolvedValue([
            { id: "source", label: "Source", uri_root: SOURCE_URI, doc: "", browsable: true, writable: false },
        ] as never);
        vi.mocked(browseRemoteFiles).mockImplementation(async (uri, _rec, _write, _limit, offset) =>
            listing(uri, offset ?? 0),
        );
    });

    afterEach(() => {
        vi.useRealTimers();
        vi.clearAllMocks();
        capabilities.server = true;
    });

    it("pages and searches a client-side source without listing it again", async () => {
        capabilities.server = false;
        const wrapper = await mountComponent();
        await clickRow(wrapper, "Source");

        await goToPage(wrapper, 2);
        expect(rowLabels(wrapper)).toEqual(["file24"]);

        await search(wrapper, "file2");
        expect(rowLabels(wrapper)).toEqual(["file2", "file20", "file21", "file22", "file23", "file24"]);

        expect(listingsOf(SOURCE_URI)).toHaveLength(1);
    });

    it("lists the file sources once after an upload started from a folder", async () => {
        const wrapper = await mountComponent();
        await clickRow(wrapper, "Source");
        await clickRow(wrapper, "folder");
        vi.mocked(fetchFileSources).mockClear();

        (wrapper.vm as unknown as { startUpload: () => void }).startUpload();
        await flushPromises();

        expect(fetchFileSources).toHaveBeenCalledTimes(1);
        expect(rowLabels(wrapper)).toEqual(["Source"]);
    });

    it("lists the source again for a search and for another page", async () => {
        const wrapper = await mountComponent();
        await clickRow(wrapper, "Source");

        await search(wrapper, "file");
        await goToPage(wrapper, 2);

        // [uri, recursive, writeable, limit, offset, query]
        expect(listingsOf(SOURCE_URI).map((call) => [call[4], call[5]])).toEqual([
            [0, undefined],
            [0, "file"],
            [25, "file"],
        ]);
    });

    it("lists a folder once when it is opened from a search", async () => {
        const wrapper = await mountComponent();
        await clickRow(wrapper, "Source");
        await search(wrapper, "fold");

        await clickRow(wrapper, "folder");

        expect(listingsOf(FOLDER_URI)).toHaveLength(1);
    });

    it("lists a folder once when it is opened from a later page", async () => {
        const wrapper = await mountComponent();
        await clickRow(wrapper, "Source");
        await goToPage(wrapper, 2);

        await clickRow(wrapper, "folder");

        expect(listingsOf(FOLDER_URI)).toHaveLength(1);
    });

    it("lists a folder once when it is opened from a later page of a search", async () => {
        const wrapper = await mountComponent();
        await clickRow(wrapper, "Source");
        await search(wrapper, "fold");
        await goToPage(wrapper, 2);

        await clickRow(wrapper, "folder");

        expect(listingsOf(FOLDER_URI)).toHaveLength(1);
    });

    it("lists the parent once when a breadcrumb is clicked during a search", async () => {
        const wrapper = await mountComponent();
        await clickRow(wrapper, "Source");
        await clickRow(wrapper, "folder");
        await search(wrapper, "inn");
        const before = listingsOf(SOURCE_URI).length;

        const crumb = wrapper.findAll("button.breadcrumb-link").filter((b) => b.text() === "Source");
        await crumb.at(0).trigger("click");
        await flushPromises();

        expect(listingsOf(SOURCE_URI).length - before).toBe(1);
    });
});
