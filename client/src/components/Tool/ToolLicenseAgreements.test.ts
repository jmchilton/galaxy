import { getLocalVue } from "@tests/vitest/helpers";
import { mount } from "@vue/test-utils";
import { describe, expect, it } from "vitest";
import { defineComponent } from "vue";

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

function mountAgreements(affirmed: string[] = [], remembered: string[] = [], agreements = [AGREEMENT]) {
    return mount(ToolLicenseAgreements as object, {
        propsData: { agreements, affirmed, remembered },
        localVue,
    });
}

describe("ToolLicenseAgreements", () => {
    it("emits affirmation", async () => {
        const wrapper = mountAgreements();
        await wrapper.find("input[data-test-id='license-affirm-test_license-input']").setValue(true);
        expect(wrapper.emitted("update:affirmed")).toEqual([[[HASH]]]);
    });

    it("clears remembering when an affirmation is withdrawn", async () => {
        const wrapper = mountAgreements([HASH], [HASH]);
        await wrapper.find("input[data-test-id='license-affirm-test_license-input']").setValue(false);
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

    it("keeps element ids unique for agreements sharing an id and across instances", async () => {
        const other = { ...AGREEMENT, agreement_hash: "c".repeat(64), terms: "Other terms." };
        // useId is unique per app, so both instances share one.
        const wrapper = mount(
            defineComponent({
                components: { ToolLicenseAgreements },
                setup: () => ({ both: [AGREEMENT, other], one: [AGREEMENT] }),
                template: `<div>
                    <ToolLicenseAgreements :agreements="both" :affirmed="[]" :remembered="[]" />
                    <ToolLicenseAgreements :agreements="one" :affirmed="[]" :remembered="[]" />
                </div>`,
            }),
            { localVue },
        );
        for (const toggle of wrapper.findAll("[data-test-id='license-terms-toggle-test_license']")) {
            await toggle.trigger("click");
        }
        const controls = wrapper.findAll("input, .license-terms-text");
        expect(controls.length).toBe(9);
        expect(new Set(controls.map((control) => control.attributes("id"))).size).toBe(9);
        for (const terms of wrapper.findAll(".license-terms")) {
            const target = terms.find("button").attributes("aria-controls");
            expect(terms.find(`#${target}`).exists()).toBe(true);
        }
    });
});
