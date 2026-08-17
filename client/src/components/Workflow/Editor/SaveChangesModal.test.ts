import { getLocalVue } from "@tests/vitest/helpers";
import { mount, type Wrapper } from "@vue/test-utils";
import flushPromises from "flush-promises";
import { describe, expect, it } from "vitest";
import type Vue from "vue";

import SaveChangesModal from "./SaveChangesModal.vue";
import GButton from "@/components/BaseComponents/GButton.vue";

const localVue = getLocalVue();

const NAV_URL = "/pages/list";

const DONT_SAVE = 1;
const SAVE = 2;

async function mountModal() {
    const wrapper = mount(SaveChangesModal as object, {
        localVue,
        propsData: { showModal: true, navUrl: NAV_URL, appendVersion: false },
        attachTo: document.body,
    });
    await flushPromises();
    return wrapper;
}

/** Cancel, Don't Save and Save in template order -- GModal's own close button carries no title. */
function footerButtons(wrapper: Wrapper<Vue>) {
    return wrapper.findAllComponents(GButton).filter((button) => Boolean(button.props("title")));
}

function disabledStates(wrapper: Wrapper<Vue>) {
    return footerButtons(wrapper).wrappers.map((button) => Boolean(button.props("disabled")));
}

describe("SaveChangesModal", () => {
    it("disables every button while the parent is handling a proceed", async () => {
        const wrapper = await mountModal();
        expect(disabledStates(wrapper)).toEqual([false, false, false]);

        await footerButtons(wrapper).at(DONT_SAVE).trigger("click");

        expect(wrapper.emitted("on-proceed")?.[0]).toEqual([NAV_URL, false, true, false]);
        expect(disabledStates(wrapper)).toEqual([true, true, true]);
    });

    it("re-enables its buttons every time it is shown again", async () => {
        // A proceed that fails to navigate leaves this instance alive; latched, it would be unusable.
        const wrapper = await mountModal();
        await footerButtons(wrapper).at(SAVE).trigger("click");
        expect(disabledStates(wrapper)).toEqual([true, true, true]);

        await wrapper.setProps({ showModal: false });
        await wrapper.setProps({ showModal: true });

        expect(disabledStates(wrapper)).toEqual([false, false, false]);
    });
});
