import { getLocalVue } from "@tests/vitest/helpers";
import { mount, RouterLinkStub, type VueWrapper } from "@vue/test-utils";
import flushPromises from "flush-promises";
import { afterEach, beforeEach, describe, expect, it } from "vitest";
import { defineComponent, h } from "vue";

import { HttpResponse, useServerMock } from "@/api/client/__mocks__";

import ItemPopoverLink from "./ItemPopoverLink.vue";
import GPopover from "@/components/BaseComponents/GPopover.vue";

const { server, http } = useServerMock();

const DATASET_ID = "dataset-id-1";
const HDCA_ID = "hdca-id-1";
const POPOVER_STUB = { name: "GPopoverStub", props: ["target"], template: "<div><slot /></div>" };
const HDCA_SUMMARY = {
    id: HDCA_ID,
    name: "my list",
    collection_type: "list",
    element_count: 3,
    elements_datatypes: ["txt"],
    populated_state: "ok",
    job_source_type: null,
    job_state_summary: { all_jobs: 3, ok: 3, populated_state: "ok" },
    contents_url: "",
    history_content_type: "dataset_collection",
    hid: 4,
    deleted: false,
    visible: true,
    history_id: "history-id-1",
    model_class: "HistoryDatasetCollectionAssociation",
    type: "collection",
    tags: [],
    create_time: "2026-01-01T00:00:00",
    update_time: "2026-01-01T00:00:00",
    collection_id: "dc-id-1",
};

let wrapper: VueWrapper | undefined;

afterEach(() => {
    wrapper?.unmount();
    wrapper = undefined;
});

function mountWith(component: object, props: Record<string, unknown> = {}, stubPopover = false) {
    const localVue = getLocalVue();
    const stubs = { ...localVue.stubs, RouterLink: RouterLinkStub, ...(stubPopover ? { GPopover: POPOVER_STUB } : {}) };
    wrapper = mount(component, { props, global: { ...localVue, stubs } });
    return wrapper;
}

describe("ItemPopoverLink ids", () => {
    it("gives two links to the same item distinct ids, each targeted by its own popover", () => {
        const Pair = defineComponent({
            render: () =>
                h("div", [
                    h(ItemPopoverLink as object, { itemId: DATASET_ID }),
                    h(ItemPopoverLink as object, { itemId: DATASET_ID }),
                ]),
        });
        const pair = mountWith(Pair);
        const links = pair.findAllComponents(ItemPopoverLink as object);
        expect(links).toHaveLength(2);
        const ids = links.map((link) => link.findComponent(RouterLinkStub).attributes("id"));
        expect(ids[0]).toBeTruthy();
        expect(ids[0]).not.toBe(ids[1]);
        links.forEach((link, index) => {
            expect(link.findComponent(GPopover).props("target")).toBe(ids[index]);
        });
    });
});

describe("ItemPopoverLink collections", () => {
    let summaryRequests: string[];
    // While set, the first collection's summary waits for it.
    let firstSummaryGate: Promise<void> | undefined;

    beforeEach(() => {
        summaryRequests = [];
        firstSummaryGate = undefined;
        server.use(
            http.get("/api/dataset_collections/{hdca_id}", async ({ request, params, response }) => {
                summaryRequests.push(new URL(request.url).searchParams.get("view") ?? "");
                if (params.hdca_id === HDCA_ID) {
                    await firstSummaryGate;
                }
                const summary =
                    params.hdca_id === HDCA_ID
                        ? HDCA_SUMMARY
                        : { ...HDCA_SUMMARY, id: params.hdca_id, name: "other list" };
                return response.untyped(HttpResponse.json(summary));
            }),
        );
    });

    function mountCollection(props: Record<string, unknown> = {}) {
        return mountWith(ItemPopoverLink as object, { itemId: HDCA_ID, itemSrc: "hdca", ...props }, true);
    }

    it("does not fetch before hover or focus", async () => {
        mountCollection({ to: "/histories/view?id=history-id-1" });
        await flushPromises();
        expect(summaryRequests).toEqual([]);
    });

    it("fetches the collection summary on focus and describes it", async () => {
        const host = mountCollection({ to: "/histories/view?id=history-id-1" });
        const link = host.findComponent(RouterLinkStub);
        expect(link.props("to")).toBe("/histories/view?id=history-id-1");
        await link.trigger("focus");
        await flushPromises();
        expect(summaryRequests).toEqual(["collection"]);
        const body = host.find(".item-details-popover").text().replace(/\s+/g, " ");
        expect(body).toContain("my list");
        expect(body).toContain("a list with 3 txt datasets");
    });

    it("describes the new collection when the item changes", async () => {
        const host = mountCollection({ to: "/histories/view?id=history-id-1" });
        await host.findComponent(RouterLinkStub).trigger("focus");
        await flushPromises();
        expect(host.find(".item-details-popover").text()).toContain("my list");
        await host.setProps({ itemId: "hdca-id-2" });
        await host.findComponent(RouterLinkStub).trigger("focus");
        await flushPromises();
        expect(summaryRequests).toHaveLength(2);
        expect(host.find(".item-details-popover").text()).toContain("other list");
        expect(host.find(".item-details-popover").text()).not.toContain("my list");
    });

    it("ignores a summary that lands after the item changed", async () => {
        let release: () => void = () => {};
        firstSummaryGate = new Promise((resolve) => (release = resolve));
        const host = mountCollection({ to: "/histories/view?id=history-id-1" });
        await host.findComponent(RouterLinkStub).trigger("focus");
        await flushPromises();
        await host.setProps({ itemId: "hdca-id-2" });
        await host.findComponent(RouterLinkStub).trigger("focus");
        await flushPromises();
        release();
        await flushPromises();
        expect(summaryRequests).toHaveLength(2);
        const body = host.find(".item-details-popover").text();
        expect(body).toContain("other list");
        expect(body).not.toContain("my list");
    });

    it("renders a button trigger when no route is given", () => {
        const host = mountCollection();
        expect(host.findComponent(RouterLinkStub).exists()).toBe(false);
        const trigger = host.find("button[type='button']");
        expect(trigger.attributes("id")).toBe(host.findComponent(POPOVER_STUB).props("target"));
        expect(trigger.attributes("aria-haspopup")).toBe("dialog");
    });
});
