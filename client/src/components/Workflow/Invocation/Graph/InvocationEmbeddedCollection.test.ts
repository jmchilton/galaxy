import { getLocalVue } from "@tests/vitest/helpers";
import { mount } from "@vue/test-utils";
import flushPromises from "flush-promises";
import { beforeEach, describe, expect, it } from "vitest";

import { HttpResponse, useServerMock } from "@/api/client/__mocks__";

import InvocationEmbeddedCollection from "./InvocationEmbeddedCollection.vue";

const { server, http } = useServerMock();

const ELEMENT_COUNT = 500;

/** The requests made, as `view` of each collection request and `limit` of each element request */
let requests: string[];

beforeEach(() => {
    requests = [];
    server.use(
        http.get("/api/dataset_collections/{hdca_id}", ({ params, query, response }) => {
            requests.push(`collection ${params.hdca_id} view=${query.get("view")}`);
            return response.untyped(
                HttpResponse.json({
                    id: params.hdca_id,
                    collection_id: "dc1",
                    name: "trimmed reads",
                    collection_type: "list",
                    element_count: ELEMENT_COUNT,
                    elements_datatypes: ["fastqsanger"],
                    elements_states: { ok: ELEMENT_COUNT },
                    elements_deleted: 0,
                    elements_purged: 0,
                    job_state_summary: {},
                    populated_state: "ok",
                }),
            );
        }),
        http.get("/api/dataset_collections/{hdca_id}/contents/{parent_id}", ({ params, query, response }) => {
            const limit = Number(query.get("limit"));
            requests.push(`elements ${params.parent_id} limit=${limit}`);
            const elements = Array.from({ length: limit }, (_, i) => ({
                id: `e${i}`,
                element_identifier: `sample_${i}`,
            }));
            return response.untyped(HttpResponse.json(elements));
        }),
    );
});

async function mountCollection() {
    const wrapper = mount(InvocationEmbeddedCollection, {
        propsData: { collectionId: "c1" },
        localVue: getLocalVue(),
    });
    await flushPromises();
    return wrapper;
}

describe("InvocationEmbeddedCollection", () => {
    it("summarizes a collection with its first elements, without loading every element", async () => {
        const wrapper = await mountCollection();

        expect(requests).toEqual(["collection c1 view=collection", "elements dc1 limit=2"]);
        expect(wrapper.text()).toContain("trimmed reads");
        expect(wrapper.text()).toContain(`a list with ${ELEMENT_COUNT}`);
        const elements = wrapper.findAll("[data-description='invocation embedded collection element']");
        expect(elements.map((element) => element.text())).toEqual(["sample_0", "sample_1"]);
        expect(wrapper.text()).toContain(`and ${ELEMENT_COUNT - 2} more`);
    });
});
