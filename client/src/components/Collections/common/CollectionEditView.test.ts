import { getLocalVue } from "@tests/vitest/helpers";
import { mount, type VueWrapper } from "@vue/test-utils";
import flushPromises from "flush-promises";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { HttpResponse, useServerMock } from "@/api/client/__mocks__";
import { getUploadDatatypes, getUploadDbKeys } from "@/components/Upload/utils";
import { setMockConfig } from "@/composables/__mocks__/config";

import CollectionEditView from "./CollectionEditView.vue";
import ChangeDatatypeTab from "@/components/Collections/common/ChangeDatatypeTab.vue";
import DatabaseEditTab from "@/components/Collections/common/DatabaseEditTab.vue";

vi.mock("@/composables/config");
vi.mock("@/components/Upload/utils", async (importOriginal) => ({
    ...(await importOriginal<object>()),
    getUploadDatatypes: vi.fn(),
    getUploadDbKeys: vi.fn(),
}));

const { server, http } = useServerMock();

const COLLECTION_ID = "collection_id";
const DATATYPES = [{ id: "bed", text: "bed", description: null, description_url: null }];
const DBKEYS = [{ id: "hg38", text: "Human hg38" }];

describe("CollectionEditView", () => {
    let wrapper: VueWrapper;

    beforeEach(() => {
        vi.clearAllMocks();
        setMockConfig({ enable_celery_tasks: true });
        server.use(
            http.untyped.get("/api/dataset_collections/:id", () =>
                HttpResponse.json({ id: COLLECTION_ID, name: "Collection", elements: [] }),
            ),
            http.untyped.get("/api/dataset_collections/:id/attributes", () =>
                HttpResponse.json({ dbkey: "hg38", extension: "bed" }),
            ),
            http.untyped.get("/api/dataset_collections/:id/suitable_converters", () => HttpResponse.json([])),
        );
    });

    afterEach(() => {
        wrapper.unmount();
    });

    async function mountView() {
        wrapper = mount(CollectionEditView as object, {
            global: {
                ...getLocalVue(),
                stubs: {
                    FormDisplay: true,
                    DatabaseEditTab: true,
                    ChangeDatatypeTab: true,
                },
            },
            props: { collectionId: COLLECTION_ID },
        });
        await flushPromises();
    }

    it("shows load errors in place of the Database/Build and datatype tabs", async () => {
        vi.mocked(getUploadDbKeys).mockRejectedValue(new Error("genomes unavailable"));
        vi.mocked(getUploadDatatypes).mockRejectedValue(new Error("datatypes unavailable"));
        await mountView();
        expect(wrapper.text()).toContain("Unable to load Database/Builds: genomes unavailable");
        expect(wrapper.text()).toContain("Unable to load datatypes: datatypes unavailable");
        expect(wrapper.findComponent(DatabaseEditTab).exists()).toBe(false);
        expect(wrapper.findComponent(ChangeDatatypeTab).exists()).toBe(false);
    });

    it("passes loaded Database/Builds and datatypes to their tabs", async () => {
        vi.mocked(getUploadDbKeys).mockResolvedValue(DBKEYS);
        vi.mocked(getUploadDatatypes).mockResolvedValue(DATATYPES);
        await mountView();
        expect(wrapper.text()).not.toContain("Unable to load");
        expect(wrapper.findComponent(DatabaseEditTab).props("genomes")).toEqual(DBKEYS);
        expect(wrapper.findComponent(ChangeDatatypeTab).props("datatypes")).toEqual(DATATYPES);
    });
});
