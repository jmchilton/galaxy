import { mount } from "@vue/test-utils";
import flushPromises from "flush-promises";
import { createPinia, setActivePinia } from "pinia";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { defineComponent } from "vue";

import { getUploadDbKeys } from "@/components/Upload/utils";
import { useDbKeyStore } from "@/stores/dbKeyStore";

import { useUploadDbKeys } from "./dbKeys";

vi.mock("@/components/Upload/utils", async (importOriginal) => ({
    ...(await importOriginal<object>()),
    getUploadDbKeys: vi.fn(),
}));

const DBKEYS = [
    { id: "?", text: "unspecified (?)" },
    { id: "hg38", text: "Human hg38" },
];

function mountUploadDbKeys() {
    let result: ReturnType<typeof useUploadDbKeys>;
    const wrapper = mount(
        defineComponent({
            setup() {
                result = useUploadDbKeys();
                return {};
            },
            template: "<div />",
        }),
    );
    return { wrapper, result: result! };
}

describe("useUploadDbKeys", () => {
    beforeEach(() => {
        setActivePinia(createPinia());
        vi.clearAllMocks();
    });

    it("loads upload dbkeys", async () => {
        vi.mocked(getUploadDbKeys).mockResolvedValue(DBKEYS);
        const { wrapper, result } = mountUploadDbKeys();
        expect(result.loading.value).toBe(true);
        await flushPromises();
        expect(result.loading.value).toBe(false);
        expect(result.error.value).toBeNull();
        expect(result.dbKeys.value.map((dbKey) => dbKey.id)).toEqual(["?", "hg38"]);
        wrapper.unmount();
    });

    it("exposes the error when upload dbkeys fail to load", async () => {
        vi.mocked(getUploadDbKeys).mockRejectedValue(new Error("unavailable"));
        const { wrapper, result } = mountUploadDbKeys();
        await flushPromises();
        expect(result.loading.value).toBe(false);
        expect(result.error.value).toBe("unavailable");
        expect(result.dbKeys.value).toEqual([]);
        wrapper.unmount();
    });

    it("clears an earlier error once a later load succeeds", async () => {
        vi.mocked(getUploadDbKeys).mockRejectedValueOnce(new Error("unavailable")).mockResolvedValue(DBKEYS);
        const first = mountUploadDbKeys();
        await flushPromises();
        expect(first.result.error.value).toBe("unavailable");
        const second = mountUploadDbKeys();
        await flushPromises();
        expect(second.result.error.value).toBeNull();
        expect(first.result.error.value).toBeNull();
        expect(first.result.loading.value).toBe(false);
        expect(first.result.dbKeys.value.map((item) => item.id)).toEqual(["?", "hg38"]);
        first.wrapper.unmount();
        second.wrapper.unmount();
    });

    it("does not reload upload dbkeys once loaded", async () => {
        vi.mocked(getUploadDbKeys).mockResolvedValue(DBKEYS);
        const first = mountUploadDbKeys();
        await flushPromises();
        const loaded = first.result.dbKeys.value;
        const second = mountUploadDbKeys();
        await flushPromises();
        expect(getUploadDbKeys).toHaveBeenCalledTimes(1);
        expect(second.result.loading.value).toBe(false);
        expect(first.result.dbKeys.value).toBe(loaded);
        first.wrapper.unmount();
        second.wrapper.unmount();
    });

    it("clears an error recorded while a load was pending once it succeeds", async () => {
        let resolveLoad: (value: typeof DBKEYS) => void;
        vi.mocked(getUploadDbKeys).mockReturnValue(new Promise((resolve) => (resolveLoad = resolve)));
        const { wrapper, result } = mountUploadDbKeys();
        useDbKeyStore().uploadDbKeysError = "unavailable";
        resolveLoad!(DBKEYS);
        await flushPromises();
        expect(result.error.value).toBeNull();
        expect(result.loading.value).toBe(false);
        wrapper.unmount();
    });
});
