import { beforeEach, describe, expect, it, onTestFinished, vi } from "vitest";

import { HttpResponse, useServerMock } from "@/api/client/__mocks__";

const { server, http } = useServerMock();

// Upload utils cache datatypes at module scope, so reload all modules for each test.
async function createDatatypeStore() {
    const { createPinia, disposePinia, setActivePinia } = await import("pinia");
    const pinia = createPinia();
    setActivePinia(pinia);
    // Capture cleanup from this freshly imported Pinia module, before importing the store.
    onTestFinished(() => {
        disposePinia(pinia);
        setActivePinia(undefined);
    });
    const { useDatatypeStore } = await import("./datatypeStore");
    return useDatatypeStore(pinia);
}

describe("useDatatypeStore", () => {
    beforeEach(() => {
        vi.resetModules();
        server.use(
            http.get("/api/datatypes", ({ response }) =>
                response.untyped(HttpResponse.json({ err_msg: "unavailable", err_code: 0 }, { status: 500 })),
            ),
        );
    });

    it("rejects fetchUploadDatatypes when the request fails", async () => {
        const store = await createDatatypeStore();
        await expect(store.fetchUploadDatatypes()).rejects.toThrow("unavailable");
        expect(store.getUploadDatatypes).toEqual([]);
    });
});
