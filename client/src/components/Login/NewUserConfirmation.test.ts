import { getLocalVue, nth, withPlugins } from "@tests/vitest/helpers";
import { enableAutoUnmount, mount, type VueWrapper } from "@vue/test-utils";
import flushPromises from "flush-promises";
import { createPinia, disposePinia } from "pinia";
import { afterEach, beforeEach, describe, expect, it, onTestFinished } from "vitest";
import { createMemoryHistory, createRouter } from "vue-router";

import { HttpResponse, useServerMock } from "@/api/client/__mocks__";

import NewUserConfirmation from "./NewUserConfirmation.vue";

const localVue = getLocalVue(true);
const { server, http } = useServerMock();

interface PostRequest {
    url: string;
}

let postRequests: PostRequest[] = [];
let originalSearchDescriptor: PropertyDescriptor | undefined;

describe("NewUserConfirmation", () => {
    let wrapper: VueWrapper<InstanceType<typeof NewUserConfirmation>>;

    beforeEach(async () => {
        postRequests = [];

        originalSearchDescriptor = Object.getOwnPropertyDescriptor(window.location, "search");
        const pinia = createPinia();
        onTestFinished(() => disposePinia(pinia));
        const router = createRouter({
            history: createMemoryHistory(),
            routes: [{ path: "/:pathMatch(.*)*", component: { template: "<div></div>" } }],
        });
        await router.push("/new-user-confirmation");

        Object.defineProperty(window.location, "search", {
            configurable: true,
            writable: true,
            value: "?provider=test_provider&provider_token=sample_token",
        });

        server.use(
            http.untyped.post(/.*/, async ({ request }) => {
                postRequests.push({ url: request.url });
                return HttpResponse.json({});
            }),
        );

        wrapper = mount(NewUserConfirmation, {
            global: withPlugins(localVue, pinia, router),
        });
    });

    afterEach(() => {
        if (originalSearchDescriptor) {
            Object.defineProperty(window.location, "search", originalSearchDescriptor);
        } else {
            Reflect.deleteProperty(window.location, "search");
        }
    });
    enableAutoUnmount(afterEach);

    it("requires accepted terms to create an account and displays registration details", async () => {
        const cardHeader = wrapper.get(".card-header");
        expect(cardHeader.text()).toBe("Confirm new account creation");

        const inputs = wrapper.findAll("input");
        expect(inputs.length).toBe(1);

        const checkField = nth(inputs, 0);
        expect(checkField.attributes("type")).toBe("checkbox");

        const submitButton = wrapper.get("button[name='confirm']");
        await submitButton.trigger("click");
        await flushPromises();

        expect(postRequests.length).toBe(0);

        await checkField.setValue(true);

        await submitButton.trigger("click");
        await flushPromises();

        expect(postRequests.length).toBe(1);
        expect(postRequests[0]?.url).toContain("/authnz/test_provider/create_user");
        expect(postRequests[0]?.url).toContain("token=sample_token");

        await wrapper.setProps({ registrationWarningMessage: "registration warning message" });

        const alert = wrapper.get(".alert");
        expect(alert.text()).toBe("registration warning message");

        await wrapper.setProps({ termsUrl: "terms_url" });

        const termsFrame = wrapper.get("iframe");
        expect(termsFrame.attributes("src")).toBe("terms_url");

        const toggle = "a[id=login-toggle]";
        const loginToggle = wrapper.get(toggle);
        expect(loginToggle.text()).toBe("Log in here.");
    });
});
