import { mount } from "@vue/test-utils";
import flushPromises from "flush-promises";
import { createPinia, setActivePinia } from "pinia";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { defineComponent } from "vue";

import { getUploadDatatypes } from "@/components/Upload/utils";

import { useUploadDatatypes } from "./datatypes";

vi.mock("@/components/Upload/utils", async (importOriginal) => ({
    ...(await importOriginal<object>()),
    getUploadDatatypes: vi.fn(),
}));

const DATATYPES = [
    { id: "auto", text: "Auto-detect", description: null, description_url: null },
    { id: "bed", text: "bed", description: "BED", description_url: null },
];

function mountUploadDatatypes() {
    let result: ReturnType<typeof useUploadDatatypes>;
    const wrapper = mount(
        defineComponent({
            setup() {
                result = useUploadDatatypes();
                return {};
            },
            template: "<div />",
        }),
    );
    return { wrapper, result: result! };
}

describe("useUploadDatatypes", () => {
    beforeEach(() => {
        setActivePinia(createPinia());
        vi.clearAllMocks();
    });

    it("loads upload datatypes", async () => {
        vi.mocked(getUploadDatatypes).mockResolvedValue(DATATYPES);
        const { wrapper, result } = mountUploadDatatypes();
        expect(result.loading.value).toBe(true);
        await flushPromises();
        expect(result.loading.value).toBe(false);
        expect(result.error.value).toBeNull();
        expect(result.datatypes.value.map((datatype) => datatype.id)).toEqual(["auto", "bed"]);
        wrapper.unmount();
    });

    it("exposes the error when upload datatypes fail to load", async () => {
        vi.mocked(getUploadDatatypes).mockRejectedValue(new Error("unavailable"));
        const { wrapper, result } = mountUploadDatatypes();
        await flushPromises();
        expect(result.loading.value).toBe(false);
        expect(result.error.value).toBe("unavailable");
        expect(result.datatypes.value).toEqual([]);
        wrapper.unmount();
    });

    it("clears an earlier error once a later load succeeds", async () => {
        vi.mocked(getUploadDatatypes).mockRejectedValueOnce(new Error("unavailable")).mockResolvedValue(DATATYPES);
        const first = mountUploadDatatypes();
        await flushPromises();
        expect(first.result.error.value).toBe("unavailable");
        const second = mountUploadDatatypes();
        await flushPromises();
        expect(second.result.error.value).toBeNull();
        expect(first.result.error.value).toBeNull();
        expect(first.result.loading.value).toBe(false);
        expect(first.result.datatypes.value.map((item) => item.id)).toEqual(["auto", "bed"]);
        first.wrapper.unmount();
        second.wrapper.unmount();
    });

    it("does not reload upload datatypes once loaded", async () => {
        vi.mocked(getUploadDatatypes).mockResolvedValue(DATATYPES);
        const first = mountUploadDatatypes();
        await flushPromises();
        const loaded = first.result.datatypes.value;
        const second = mountUploadDatatypes();
        await flushPromises();
        expect(getUploadDatatypes).toHaveBeenCalledTimes(1);
        expect(second.result.loading.value).toBe(false);
        expect(first.result.datatypes.value).toBe(loaded);
        first.wrapper.unmount();
        second.wrapper.unmount();
    });

    it("clears the error from an older failed load once a newer load succeeds", async () => {
        let rejectOlder: (error: Error) => void;
        let resolveNewer: (value: typeof DATATYPES) => void;
        vi.mocked(getUploadDatatypes)
            .mockReturnValueOnce(new Promise((_resolve, reject) => (rejectOlder = reject)))
            .mockReturnValueOnce(new Promise((resolve) => (resolveNewer = resolve)));
        const older = mountUploadDatatypes();
        const newer = mountUploadDatatypes();
        rejectOlder!(new Error("unavailable"));
        await flushPromises();
        expect(newer.result.error.value).toBe("unavailable");
        resolveNewer!(DATATYPES);
        await flushPromises();
        expect(newer.result.error.value).toBeNull();
        expect(newer.result.loading.value).toBe(false);
        expect(newer.result.datatypes.value.map((item) => item.id)).toEqual(["auto", "bed"]);
        older.wrapper.unmount();
        newer.wrapper.unmount();
    });
});
