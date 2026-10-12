import { getLocalVue } from "@tests/vitest/helpers";
import { enableAutoUnmount, mount } from "@vue/test-utils";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { defineComponent, h, type PropType } from "vue";

import { sanitizeHtml } from "@/directives/sanitizeHtml";

import { useWizard } from "./useWizard";

import GenericWizard from "./GenericWizard.vue";

const WizardHost = defineComponent({
    props: {
        description: { type: String, required: true },
        containerComponent: { type: String as PropType<"BCard" | "div">, default: undefined },
    },
    setup(props) {
        const wizard = useWizard({
            only: { label: "Only step", instructions: "Do it", isValid: () => true, isSkippable: () => false },
        });
        return () =>
            h(GenericWizard, {
                use: wizard,
                description: props.description,
                ...(props.containerComponent ? { containerComponent: props.containerComponent } : {}),
            });
    },
});

beforeEach(() => vi.mocked(sanitizeHtml).mockClear());
enableAutoUnmount(afterEach);

const global = getLocalVue();

describe("GenericWizard", () => {
    it("renders the description markdown through v-sanitize-html with the links profile", () => {
        mount(WizardHost, {
            global,
            props: { description: "Pick **one** of the [options](https://example.org)" },
        });

        const descriptionCall = vi.mocked(sanitizeHtml).mock.calls.find(([html]) => html?.includes(">options</a>"));
        expect(descriptionCall?.[1]).toBe("links");
        expect(descriptionCall?.[0]).toContain("<strong>one</strong>");
        expect(descriptionCall?.[0]).toContain('target="_blank"');
    });

    it("wraps the wizard in a card by default", () => {
        const wrapper = mount(WizardHost, { global, props: { description: "Pick one" } });

        const container = wrapper.get(".wizard-container");
        expect(container.element.tagName).toBe("DIV");
        expect(container.classes()).toContain("card");
    });

    it("uses a plain div when asked to", () => {
        const wrapper = mount(WizardHost, {
            global,
            props: { description: "Pick one", containerComponent: "div" },
        });

        const container = wrapper.get(".wizard-container");
        expect(container.element.tagName).toBe("DIV");
        expect(container.classes()).not.toContain("card");
    });
});
