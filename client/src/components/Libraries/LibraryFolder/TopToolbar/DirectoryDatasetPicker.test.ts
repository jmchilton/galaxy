import { getLocalVue } from "@tests/vitest/helpers";
import { mount, type VueWrapper } from "@vue/test-utils";
import flushPromises from "flush-promises";
import { afterEach, beforeEach, describe, expect, it } from "vitest";

import { HttpResponse, useServerMock } from "@/api/client/__mocks__";
import { useDbKeyStore } from "@/stores/dbKeyStore";

import DirectoryDatasetPicker from "./DirectoryDatasetPicker.vue";
import SingleItemSelector from "@/components/SingleItemSelector.vue";

const { server, http } = useServerMock();

// Text order differs from id order, so sorting by id is observable.
const GENOMES = [
    ["unspecified (?)", "?"],
    ["Alpha", "zz1"],
    ["Beta", "aa1"],
];

describe("DirectoryDatasetPicker", () => {
    let wrapper: VueWrapper;

    beforeEach(() => {
        server.use(
            http.untyped.get("/api/remote_files", () => HttpResponse.json([])),
            http.untyped.get("/api/datatypes", () => HttpResponse.json([])),
            http.untyped.get("/api/datatypes/edam_formats/detailed", () => HttpResponse.json({})),
            http.untyped.get("/api/datatypes/edam_data/detailed", () => HttpResponse.json({})),
        );
    });

    afterEach(() => {
        wrapper.unmount();
    });

    async function mountPicker() {
        wrapper = mount(DirectoryDatasetPicker as object, {
            global: { ...getLocalVue(), stubs: { FormDrilldown: true, SingleItemSelector: true } },
            props: { folderId: "folder_id", target: "userdir" },
        });
        await flushPromises();
    }

    function findDbKeySelector() {
        return wrapper
            .findAllComponents(SingleItemSelector)
            .find((selector) => selector.props("collectionName") === "DB Keys");
    }

    // Loaded genomes are cached at module scope, so the failure case runs first.
    it("shows an error instead of the Database/Build selector when Database/Builds fail to load", async () => {
        server.use(
            http.get("/api/genomes", ({ response }) =>
                response.untyped(HttpResponse.json({ err_msg: "unavailable", err_code: 0 }, { status: 500 })),
            ),
        );
        await mountPicker();
        expect(wrapper.text()).toContain("Unable to load Database/Builds: unavailable");
        expect(findDbKeySelector()).toBeUndefined();
    });

    describe("with Database/Builds loaded", () => {
        beforeEach(async () => {
            server.use(http.untyped.get("/api/genomes", () => HttpResponse.json(GENOMES)));
            await mountPicker();
        });

        it("lists Database/Builds sorted by id with unspecified selected", () => {
            const selector = findDbKeySelector()!;
            const items = selector.props("items") as { id: string }[];
            expect(items.map((item) => item.id)).toEqual(["?", "aa1", "zz1"]);
            expect(selector.props("currentItem")).toEqual({ id: "?", text: "unspecified (?)" });
        });

        it("leaves the shared Database/Build order unchanged", () => {
            expect(useDbKeyStore().uploadDbKeys.map((item: { id: string }) => item.id)).toEqual(["?", "zz1", "aa1"]);
        });
    });
});
