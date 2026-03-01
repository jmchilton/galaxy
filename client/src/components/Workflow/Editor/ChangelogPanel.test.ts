import { getLocalVue } from "@tests/vitest/helpers";
import { shallowMount, type Wrapper } from "@vue/test-utils";
import flushPromises from "flush-promises";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { type ChangelogEntry, getChangelog } from "@/api/workflows";

import ChangelogPanel from "./ChangelogPanel.vue";

vi.mock("@/api/workflows", () => ({
    getChangelog: vi.fn(),
}));

const localVue = getLocalVue();

function makeEntry(overrides: Partial<ChangelogEntry> = {}): ChangelogEntry {
    return {
        id: "entry1",
        title: "Update step",
        source_action_type: "editor_save",
        create_time: "2026-02-28T12:00:00Z",
        user_id: "user1",
        workflow_id_before: "wf_v1",
        workflow_id_after: "wf_v2",
        execution_messages: [],
        is_revert: false,
        reverted_entry_id: null,
        ...overrides,
    } as ChangelogEntry;
}

describe("ChangelogPanel.vue", () => {
    let wrapper: Wrapper<Vue>;

    function mountPanel() {
        return shallowMount(ChangelogPanel as object, {
            propsData: {
                workflowId: "test-wf-id",
            },
            localVue,
        });
    }

    beforeEach(() => {
        vi.clearAllMocks();
    });

    it("renders loading state initially", async () => {
        vi.mocked(getChangelog).mockReturnValue(new Promise(() => {})); // never resolves
        wrapper = mountPanel();
        await wrapper.vm.$nextTick();
        // shallowMount stubs child components — verify LoadingSpan stub is present
        expect(wrapper.findComponent({ name: "LoadingSpan" }).exists()).toBe(true);
    });

    it("renders empty state when no entries", async () => {
        vi.mocked(getChangelog).mockResolvedValue({ data: [], totalMatches: 0 });
        wrapper = mountPanel();
        await flushPromises();

        expect(wrapper.text()).toContain("No changelog entries yet");
        expect(wrapper.find(".changelog-entry").exists()).toBe(false);
    });

    it("renders entries with title", async () => {
        const entries = [makeEntry({ id: "e1", title: "Add step" }), makeEntry({ id: "e2", title: "Update name" })];
        vi.mocked(getChangelog).mockResolvedValue({ data: entries, totalMatches: 2 });
        wrapper = mountPanel();
        await flushPromises();

        const entryEls = wrapper.findAll(".changelog-entry");
        expect(entryEls.length).toBe(2);
        expect(entryEls.at(0).find(".entry-title").text()).toBe("Add step");
        expect(entryEls.at(1).find(".entry-title").text()).toBe("Update name");
    });

    it("renders timestamp for each entry", async () => {
        vi.mocked(getChangelog).mockResolvedValue({ data: [makeEntry()], totalMatches: 1 });
        wrapper = mountPanel();
        await flushPromises();

        expect(wrapper.find(".entry-time").exists()).toBe(true);
    });

    it("revert button emits event with entry", async () => {
        const entry = makeEntry({ id: "e1" });
        vi.mocked(getChangelog).mockResolvedValue({ data: [entry], totalMatches: 1 });
        wrapper = mountPanel();
        await flushPromises();

        await wrapper.find(".entry-revert-btn").trigger("click");
        expect(wrapper.emitted().revert).toBeTruthy();
        expect(wrapper.emitted().revert![0]![0]).toEqual(entry);
    });

    it("shows Load more button when more entries exist", async () => {
        const entries = Array.from({ length: 25 }, (_, i) => makeEntry({ id: `e${i}` }));
        vi.mocked(getChangelog).mockResolvedValue({ data: entries, totalMatches: 40 });
        wrapper = mountPanel();
        await flushPromises();

        const loadMoreBtn = wrapper.find(".load-more-btn");
        expect(loadMoreBtn.exists()).toBe(true);
        expect(loadMoreBtn.text()).toContain("Load more");
    });

    it("does not show Load more when all entries loaded", async () => {
        vi.mocked(getChangelog).mockResolvedValue({ data: [makeEntry()], totalMatches: 1 });
        wrapper = mountPanel();
        await flushPromises();

        expect(wrapper.find(".load-more-btn").exists()).toBe(false);
    });

    it("load more appends entries", async () => {
        const page1 = Array.from({ length: 25 }, (_, i) => makeEntry({ id: `e${i}` }));
        const page2 = [makeEntry({ id: "e25" }), makeEntry({ id: "e26" })];

        vi.mocked(getChangelog).mockResolvedValueOnce({ data: page1, totalMatches: 27 });
        wrapper = mountPanel();
        await flushPromises();
        expect(wrapper.findAll(".changelog-entry").length).toBe(25);

        vi.mocked(getChangelog).mockResolvedValueOnce({ data: page2, totalMatches: 27 });
        await wrapper.find(".load-more-btn").trigger("click");
        await flushPromises();

        expect(wrapper.findAll(".changelog-entry").length).toBe(27);
        expect(vi.mocked(getChangelog)).toHaveBeenLastCalledWith("test-wf-id", 25, 25);
    });

    it("refresh replaces entries", async () => {
        const page1 = [makeEntry({ id: "e1", title: "Old" })];
        const page2 = [makeEntry({ id: "e2", title: "New" })];

        vi.mocked(getChangelog).mockResolvedValueOnce({ data: page1, totalMatches: 1 });
        wrapper = mountPanel();
        await flushPromises();
        expect(wrapper.find(".entry-title").text()).toBe("Old");

        vi.mocked(getChangelog).mockResolvedValueOnce({ data: page2, totalMatches: 1 });
        (wrapper.vm as any).refresh();
        await flushPromises();

        expect(wrapper.findAll(".changelog-entry").length).toBe(1);
        expect(wrapper.find(".entry-title").text()).toBe("New");
    });

    it("renders error state", async () => {
        vi.mocked(getChangelog).mockRejectedValue(new Error("Network error"));
        wrapper = mountPanel();
        await flushPromises();

        expect(wrapper.find(".alert-danger").exists()).toBe(true);
        expect(wrapper.text()).toContain("Network error");
    });

    it("shows revert badge for revert entries", async () => {
        vi.mocked(getChangelog).mockResolvedValue({
            data: [makeEntry({ is_revert: true })],
            totalMatches: 1,
        });
        wrapper = mountPanel();
        await flushPromises();

        expect(wrapper.find(".entry-badge").exists()).toBe(true);
        expect(wrapper.find(".entry-badge").text()).toContain("revert");
    });

    it("does not show revert badge for non-revert entries", async () => {
        vi.mocked(getChangelog).mockResolvedValue({
            data: [makeEntry({ is_revert: false })],
            totalMatches: 1,
        });
        wrapper = mountPanel();
        await flushPromises();

        expect(wrapper.find(".entry-badge").exists()).toBe(false);
    });
});
