import { getLocalVue } from "@tests/jest/helpers";
import { mount } from "@vue/test-utils";
import flushPromises from "flush-promises";

import { HttpResponse, useServerMock } from "@/api/client/__mocks__";

import TrsSearch from "./TrsSearch.vue";

jest.mock("vue-router/composables", () => ({
    useRouter: jest.fn(() => ({})),
}));

const localVue = getLocalVue(true);
const { server, http } = useServerMock();

const TRS_SERVERS = [
    { id: "dockstore", label: "dockstore", link_url: "https://dockstore.org", doc: "Dockstore" },
    { id: "workflowhub", label: "workflowhub", link_url: "https://workflowhub.eu", doc: "WorkflowHub" },
];
const QUERY = "organization: iwc-workflows";
// longer than the 500 ms debounce of the search input
const DEBOUNCE_WAIT = 600;

function wait(ms: number) {
    return new Promise((resolve) => setTimeout(resolve, ms));
}

describe("TrsSearch", () => {
    it("keeps a query typed before the TRS server list loads and searches it on that server", async () => {
        let resolveServers: () => void = () => {};
        const serversLoaded = new Promise<void>((resolve) => {
            resolveServers = resolve;
        });
        const searches: { query: string | null; trsServer: string | null }[] = [];
        server.use(
            http.untyped.get("/api/trs_consume/servers", async () => {
                await serversLoaded;
                return HttpResponse.json(TRS_SERVERS);
            }),
            http.untyped.get("/api/trs_search", ({ request }) => {
                const params = new URL(request.url).searchParams;
                searches.push({ query: params.get("query"), trsServer: params.get("trs_server") });
                return HttpResponse.json([]);
            }),
        );

        const wrapper = mount(TrsSearch as object, { localVue });
        const input = wrapper.find("#trs-search-query");
        await input.setValue(QUERY);
        await wait(DEBOUNCE_WAIT);
        await flushPromises();

        // no server is selected yet, so there is nothing to search
        expect(searches).toEqual([]);

        resolveServers();
        await wait(50);
        await flushPromises();

        expect((input.element as HTMLInputElement).value).toBe(QUERY);
        expect(searches).toEqual([{ query: QUERY, trsServer: "dockstore" }]);
    });

    it("clears the query when switching to another TRS server", async () => {
        const searches: (string | null)[] = [];
        server.use(
            http.untyped.get("/api/trs_consume/servers", () => HttpResponse.json(TRS_SERVERS)),
            http.untyped.get("/api/trs_search", ({ request }) => {
                searches.push(new URL(request.url).searchParams.get("trs_server"));
                return HttpResponse.json([{ id: "dockstore-result", name: "dockstore workflow", description: "" }]);
            }),
        );

        const wrapper = mount(TrsSearch as object, { localVue });
        await flushPromises();
        const input = wrapper.find("#trs-search-query");
        await input.setValue(QUERY);
        await wait(DEBOUNCE_WAIT);
        await flushPromises();
        expect((input.element as HTMLInputElement).value).toBe(QUERY);
        expect(wrapper.text()).toContain("dockstore workflow");

        const workflowhub = wrapper.findAll(".dropdown-item").filter((item) => item.text() === "workflowhub");
        await workflowhub.at(0).trigger("click");
        await wait(DEBOUNCE_WAIT);
        await flushPromises();

        expect((input.element as HTMLInputElement).value).toBe("");
        expect(searches).toEqual(["dockstore"]);
        expect(wrapper.text()).not.toContain("dockstore workflow");
    });

    it("ignores a response to a search that a newer search replaced", async () => {
        let resolveFirst: () => void = () => {};
        const firstHeld = new Promise<void>((resolve) => {
            resolveFirst = resolve;
        });
        server.use(
            http.untyped.get("/api/trs_consume/servers", () => HttpResponse.json(TRS_SERVERS)),
            http.untyped.get("/api/trs_search", async ({ request }) => {
                const query = new URL(request.url).searchParams.get("query");
                if (query === "first") {
                    await firstHeld;
                }
                return HttpResponse.json([{ id: query, name: `${query} workflow`, description: "" }]);
            }),
        );

        const wrapper = mount(TrsSearch as object, { localVue });
        await flushPromises();
        const input = wrapper.find("#trs-search-query");
        await input.setValue("first");
        await wait(DEBOUNCE_WAIT);
        await input.setValue("second");
        await wait(DEBOUNCE_WAIT);
        await flushPromises();
        expect(wrapper.text()).toContain("second workflow");

        resolveFirst();
        await wait(50);
        await flushPromises();

        expect(wrapper.text()).toContain("second workflow");
        expect(wrapper.text()).not.toContain("first workflow");
        expect(wrapper.text()).not.toContain("Searching for");
    });
});
