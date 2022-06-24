import { mount } from "@vue/test-utils";
import { getLocalVue } from "jest/helpers";
import UserPreferredObjectStore from "./UserPreferredObjectStore";
import axios from "axios";
import MockAdapter from "axios-mock-adapter";
import flushPromises from "flush-promises";

const localVue = getLocalVue(true);

const TEST_USER_ID = "myTestUserId";
const TEST_ROOT = "/";

function mountComponent() {
    const wrapper = mount(UserPreferredObjectStore, {
        propsData: { userId: TEST_USER_ID, root: TEST_ROOT },
        localVue,
        stubs: { "b-popover": true },
    });
    return wrapper;
}

import { ROOT_COMPONENT } from "utils/navigation";

const OBJECT_STORES = [
    { object_store_id: "object_store_1", badges: [], quota: { enabled: false } },
    { object_store_id: "object_store_2", badges: [], quota: { enabled: false } },
];

describe("UserPreferredObjectStore.vue", () => {
    let axiosMock;

    beforeEach(async () => {
        axiosMock = new MockAdapter(axios);
        axiosMock.onGet("/api/object_store?selectable=true").reply(200, OBJECT_STORES);
    });

    afterEach(async () => {
        axiosMock.restore();
    });

    it("contains a localized link", async () => {
        const wrapper = mountComponent();
        expect(wrapper.vm.$refs["modal"].isHidden).toBeTruthy();
        const el = await wrapper.find(ROOT_COMPONENT.preferences.object_store.selector);
        expect(el.text()).toBeLocalizationOf("Preferred Object Store");
        await el.trigger("click");
        expect(wrapper.vm.$refs["modal"].isHidden).toBeFalsy();
    });

    it("updates object store to default on selection null", async () => {
        const wrapper = mountComponent();
        const el = await wrapper.find(ROOT_COMPONENT.preferences.object_store.selector);
        await el.trigger("click");
        const els = wrapper.findAll(ROOT_COMPONENT.preferences.object_store_selection.option_buttons.selector);
        expect(els.length).toBe(3);
        const galaxyDefaultOption = wrapper.find(
            ROOT_COMPONENT.preferences.object_store_selection.option_button({ object_store_id: "__null__" }).selector
        );
        expect(galaxyDefaultOption.exists()).toBeTruthy();
        axiosMock.onPut("/api/users/current", expect.objectContaining({ preferred_object_store_id: null })).reply(202);
        await galaxyDefaultOption.trigger("click");
        expect(wrapper.vm.$data.error).toBeNull();
    });

    it("updates object store to default on selection null", async () => {
        const wrapper = mountComponent();
        const el = await wrapper.find(ROOT_COMPONENT.preferences.object_store.selector);
        await el.trigger("click");
        const objectStore2Option = wrapper.find(
            ROOT_COMPONENT.preferences.object_store_selection.option_button({ object_store_id: "object_store_2" })
                .selector
        );
        expect(objectStore2Option.exists()).toBeTruthy();
        axiosMock
            .onPut("/api/users/current", expect.objectContaining({ preferred_object_store_id: "object_store_2" }))
            .reply(202);
        await objectStore2Option.trigger("click");
        expect(wrapper.vm.$data.error).toBeNull();
    });

    it("displayed error is user update fails", async () => {
        const wrapper = mountComponent();
        const el = await wrapper.find(ROOT_COMPONENT.preferences.object_store.selector);
        await el.trigger("click");
        const galaxyDefaultOption = wrapper.find(
            ROOT_COMPONENT.preferences.object_store_selection.option_button({ object_store_id: "__null__" }).selector
        );
        expect(galaxyDefaultOption.exists()).toBeTruthy();
        axiosMock
            .onPut("/api/users/current", expect.objectContaining({ preferred_object_store_id: null }))
            .reply(400, { err_msg: "problem with selection.." });
        await galaxyDefaultOption.trigger("click");
        await flushPromises();
        const errorEl = await wrapper.find(".object-store-selection-error");
        expect(errorEl.exists()).toBeTruthy();
        expect(wrapper.vm.error).toBe("problem with selection..");
    });
});
