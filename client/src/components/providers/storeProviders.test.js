import { getLocalVue } from "@tests/vitest/helpers";
import { mount } from "@vue/test-utils";
import flushPromises from "flush-promises";
import { createPinia, setActivePinia } from "pinia";
import { afterEach, beforeEach, describe, expect, it } from "vitest";
import { h } from "vue";

import { HttpResponse, useServerMock } from "@/api/client/__mocks__";

import { DatatypesProvider, DbKeyProvider } from "./storeProviders";

const localVue = getLocalVue();
const { server, http } = useServerMock();

function mountProvider(provider) {
    return mount(provider, {
        global: localVue,
        props: { id: "provider" },
        slots: {
            default: (props) =>
                h("div", [
                    h("span", { class: "state" }, String(props.loading)),
                    h("span", { class: "error" }, props.error ?? ""),
                ]),
        },
    });
}

describe("DatatypesProvider", () => {
    let wrapper;
    let datatypesRequests;

    beforeEach(() => {
        setActivePinia(createPinia());
        datatypesRequests = 0;
    });

    afterEach(() => {
        wrapper?.unmount();
    });

    it("stops loading and exposes the error when fetching datatypes fails", async () => {
        server.use(
            http.get("/api/datatypes", ({ response }) => {
                datatypesRequests++;
                return response.untyped(HttpResponse.json({ err_msg: "unavailable", err_code: 0 }, { status: 500 }));
            }),
        );
        wrapper = mountProvider(DatatypesProvider);
        await flushPromises();
        expect(datatypesRequests).toBe(1);
        expect(wrapper.find(".state").text()).toBe("false");
        expect(wrapper.find(".error").text()).toContain("unavailable");
    });

    it("exposes no error when fetching datatypes succeeds", async () => {
        server.use(
            http.get("/api/datatypes", ({ response }) => {
                datatypesRequests++;
                return response.untyped(HttpResponse.json([]));
            }),
        );
        wrapper = mountProvider(DatatypesProvider);
        await flushPromises();
        expect(wrapper.find(".state").text()).toBe("false");
        expect(wrapper.find(".error").text()).toBe("");
    });
});

describe("DbKeyProvider", () => {
    let wrapper;

    beforeEach(() => {
        setActivePinia(createPinia());
    });

    afterEach(() => {
        wrapper?.unmount();
    });

    // Genomes are cached at module scope once loaded, so the failure case runs first.
    it("stops loading and exposes the error when fetching dbkeys fails", async () => {
        server.use(
            http.get("/api/genomes", ({ response }) =>
                response.untyped(HttpResponse.json({ err_msg: "unavailable", err_code: 0 }, { status: 500 })),
            ),
        );
        wrapper = mountProvider(DbKeyProvider);
        await flushPromises();
        expect(wrapper.find(".state").text()).toBe("false");
        expect(wrapper.find(".error").text()).toContain("unavailable");
    });

    it("exposes no error when fetching dbkeys succeeds", async () => {
        server.use(
            http.get("/api/genomes", ({ response }) => response.untyped(HttpResponse.json([["Human hg38", "hg38"]]))),
        );
        wrapper = mountProvider(DbKeyProvider);
        await flushPromises();
        expect(wrapper.find(".state").text()).toBe("false");
        expect(wrapper.find(".error").text()).toBe("");
    });
});
