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
});
