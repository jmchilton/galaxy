import { getLocalVue, nth, withPlugins } from "@tests/vitest/helpers";
import { enableAutoUnmount, mount, type VueWrapper } from "@vue/test-utils";
import flushPromises from "flush-promises";
import { createPinia, disposePinia } from "pinia";
import { afterEach, beforeEach, describe, expect, it, onTestFinished, vi } from "vitest";
import { createMemoryHistory, createRouter } from "vue-router";

import { HttpResponse, useServerMock } from "@/api/client/__mocks__";

import NewUserConfirmation from "./NewUserConfirmation.vue";

const localVue = getLocalVue(true);
const { server, http } = useServerMock();

interface PostRequest {
    url: string;
    body: URLSearchParams;
}

let postRequests: PostRequest[] = [];
let originalSearchDescriptor: PropertyDescriptor | undefined;

describe("NewUserConfirmation", () => {
    let router: ReturnType<typeof createRouter>;
    let wrapper: VueWrapper<InstanceType<typeof NewUserConfirmation>>;

    beforeEach(async () => {
        postRequests = [];
        vi.spyOn(window.location, "assign").mockImplementation(() => {});

        originalSearchDescriptor = Object.getOwnPropertyDescriptor(window.location, "search");
        const pinia = createPinia();
        onTestFinished(() => disposePinia(pinia));
        router = createRouter({
            history: createMemoryHistory(),
            routes: [{ path: "/:pathMatch(.*)*", component: { template: "<div></div>" } }],
        });
        await router.push("/new-user-confirmation");

        Object.defineProperty(window.location, "search", {
            configurable: true,
            writable: true,
            value: "?provider=test_provider&confirmation_id=sample_confirmation",
        });

        server.use(
            http.untyped.post(/.*/, async ({ request }) => {
                postRequests.push({ url: request.url, body: new URLSearchParams(await request.text()) });
                return HttpResponse.json({});
            }),
        );

        wrapper = mount(NewUserConfirmation, {
            props: { sessionCsrfToken: "session-csrf-token" },
            global: withPlugins(localVue, pinia, router),
        });
    });

    afterEach(() => {
        vi.restoreAllMocks();
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
        expect(new URL(postRequests[0]!.url).search).toBe("");
        expect(postRequests[0]?.body.get("confirmation_id")).toBe("sample_confirmation");
        expect(postRequests[0]?.body.get("session_csrf_token")).toBe("session-csrf-token");
        expect(postRequests[0]?.body.has("token")).toBe(false);

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

    it("rejects form submission until terms are accepted", async () => {
        await wrapper.find("form").trigger("submit");
        await flushPromises();
        expect(postRequests).toHaveLength(0);
    });

    it.each([
        { root: "/", redirectUri: "/user/external_ids", expected: "/user/external_ids" },
        { root: "/galaxy", redirectUri: "/galaxy/user/external_ids", expected: "/galaxy/user/external_ids" },
        { root: "/galaxy", redirectUri: undefined, expected: "/galaxy/" },
    ])("reloads the session at $expected after confirmation", async ({ root, redirectUri, expected }) => {
        const indexLink = document.createElement("link");
        indexLink.rel = "index";
        indexLink.href = root;
        document.head.prepend(indexLink);
        try {
            server.use(http.untyped.post(/.*create_user$/, () => HttpResponse.json({ redirect_uri: redirectUri })));
            await wrapper.find("input[type='checkbox']").setValue(true);
            await wrapper.find("button[name='confirm']").trigger("click");
            await flushPromises();
            expect(window.location.assign).toHaveBeenCalledExactlyOnceWith(expected);
            expect(router.currentRoute.value.path).toBe("/new-user-confirmation");
        } finally {
            indexLink.remove();
        }
    });

    it("cancels the server confirmation before returning to login", async () => {
        await wrapper.find("button[name='cancel']").trigger("click");
        await flushPromises();
        expect(postRequests).toHaveLength(1);
        expect(postRequests[0]?.url).toContain("/cancel_user_creation");
        expect(postRequests[0]?.body.get("confirmation_id")).toBe("sample_confirmation");
        expect(postRequests[0]?.body.get("session_csrf_token")).toBe("session-csrf-token");
        expect(router.currentRoute.value.path).toBe("/login");
    });

    it("shows expiry errors without redirecting", async () => {
        server.use(
            http.untyped.post(/.*create_user$/, () =>
                HttpResponse.json(
                    { err_msg: "Authentication expired. Please start logging in again." },
                    { status: 400 },
                ),
            ),
        );
        await wrapper.find("input[type='checkbox']").setValue(true);
        await wrapper.find("button[name='confirm']").trigger("click");
        await flushPromises();
        expect(wrapper.find(".alert-danger").text()).toContain("Authentication expired");
        expect(router.currentRoute.value.path).toBe("/new-user-confirmation");
        expect(window.location.assign).not.toHaveBeenCalled();
    });

    it("prevents duplicate submissions while a request is pending", async () => {
        let finish: (() => void) | undefined;
        server.use(
            http.untyped.post(/.*create_user$/, async ({ request }) => {
                postRequests.push({ url: request.url, body: new URLSearchParams(await request.text()) });
                await new Promise<void>((resolve) => {
                    finish = resolve;
                });
                return HttpResponse.json({ redirect_uri: "/" });
            }),
        );
        await wrapper.find("input[type='checkbox']").setValue(true);
        await wrapper.find("form").trigger("submit");
        await flushPromises();
        expect(wrapper.find("button[name='confirm']").attributes("aria-disabled")).toBe("true");
        await wrapper.find("form").trigger("submit");
        await flushPromises();
        expect(postRequests).toHaveLength(1);
        finish!();
        await flushPromises();
    });

    it("never resubmits credentials from a legacy link", async () => {
        wrapper.unmount();
        Object.defineProperty(window.location, "search", {
            configurable: true,
            writable: true,
            value: "?provider=test_provider&provider_token=secret-provider-response",
        });
        wrapper = mount(NewUserConfirmation, {
            props: { sessionCsrfToken: "session-csrf-token" },
            global: withPlugins(localVue, router),
        });
        await wrapper.find("input[type='checkbox']").setValue(true);
        await wrapper.find("form").trigger("submit");
        await flushPromises();
        expect(postRequests).toHaveLength(0);
        expect(wrapper.find(".alert-danger").text()).toContain("Please start logging in again");
        expect(wrapper.text()).not.toContain("secret-provider-response");
    });
});
