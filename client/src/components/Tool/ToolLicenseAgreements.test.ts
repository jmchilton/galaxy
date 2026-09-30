import { getLocalVue } from "@tests/vitest/helpers";
import { mount } from "@vue/test-utils";
import { describe, expect, it } from "vitest";

import ToolLicenseAgreements from "./ToolLicenseAgreements.vue";

const localVue = getLocalVue();

const HASH = "b".repeat(64);

const AGREEMENT = {
    agreement_hash: HASH,
    id: "test_license",
    version: "1",
    label: "Test License",
    url: "https://example.org/license",
    affirmation: "I agree to the test license.",
    terms: "Test terms.",
    binds: "user",
    accepted: false,
};

function mountAgreements(affirmed: string[] = [], remembered: string[] = []) {
    return mount(ToolLicenseAgreements as object, {
        propsData: { agreements: [AGREEMENT], affirmed, remembered },
        localVue,
    });
}

describe("ToolLicenseAgreements", () => {
    it("emits affirmation", async () => {
        const wrapper = mountAgreements();
        await wrapper.find("input[data-test-id='license-affirm-test_license-input']").setChecked(true);
        expect(wrapper.emitted("update:affirmed")).toEqual([[[HASH]]]);
    });

    it("clears remembering when an affirmation is withdrawn", async () => {
        const wrapper = mountAgreements([HASH], [HASH]);
        await wrapper.find("input[data-test-id='license-affirm-test_license-input']").setChecked(false);
        expect(wrapper.emitted("update:affirmed")).toEqual([[[]]]);
        expect(wrapper.emitted("update:remembered")).toEqual([[[]]]);
    });

    it("shows the terms on request", async () => {
        const wrapper = mountAgreements();
        expect(wrapper.find("[data-test-id='license-terms-test_license']").exists()).toBe(false);
        const toggle = wrapper.find("[data-test-id='license-terms-toggle-test_license']");
        expect(toggle.attributes("aria-expanded")).toBe("false");
        await toggle.trigger("click");
        expect(wrapper.find("[data-test-id='license-terms-test_license']").text()).toBe("Test terms.");
        expect(toggle.attributes("aria-expanded")).toBe("true");
    });
});
