import "@tests/vitest/mockHelpPopovers";

import { getFakeRegisteredUser } from "@tests/test-data";
import { getLocalVue, injectTestRouter } from "@tests/vitest/helpers";
import { mount, type Wrapper } from "@vue/test-utils";
import flushPromises from "flush-promises";
import { createPinia } from "pinia";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { HttpResponse, useServerMock } from "@/api/client/__mocks__";
import type { AnyHistory } from "@/api/index.js";
import MockCurrentHistory from "@/components/providers/MockCurrentHistory";
import { useHistoryStore } from "@/stores/historyStore";
import { useUserStore } from "@/stores/userStore";

import ToolForm from "./ToolForm.vue";
import FormDisplay from "@/components/Form/FormDisplay.vue";

const { server, http } = useServerMock();

const localVue = getLocalVue();
const router = injectTestRouter(localVue);
const pinia = createPinia();

vi.mock("@/composables/userLocalStorageFromHashedId", async () => {
    const { ref } = await import("vue");
    return {
        useUserLocalStorageFromHashId: (_key: string, initialValue: unknown) => ref(initialValue),
    };
});

describe("ToolForm", () => {
    let wrapper: Wrapper<Vue>;
    let userStore: ReturnType<typeof useUserStore>;
    let historyStore: ReturnType<typeof useHistoryStore>;

    function mountToolForm() {
        wrapper = mount(ToolForm as object, {
            propsData: {
                id: "tool_id",
                version: "version",
            },
            localVue,
            router,
            stubs: {
                UserHistories: MockCurrentHistory({ id: "fakeHistory" }),
                FormDisplay: true,
            },
            pinia,
        });
        userStore = useUserStore();
        userStore.currentUser = getFakeRegisteredUser({ id: "fakeUser" });

        historyStore = useHistoryStore();
        historyStore.setHistories([{ id: "fakeHistory" } as AnyHistory]);
        historyStore.setCurrentHistoryId("fakeHistory");
        historyStore.startWatchingHistory = () => {};
    }

    function buildResponse(overrides = {}) {
        return {
            id: "tool_id",
            name: "tool_name",
            version: "version",
            inputs: [],
            help: "help_text",
            help_format: "restructuredtext",
            creator: [{ class: "Person", givenName: "FakeName", familyName: "FakeSurname", email: "fakeEmail" }],
            ...overrides,
        };
    }

    function useBuildResponse(overrides = {}) {
        server.use(
            http.untyped.get("/api/tools/tool_id/build", ({ request }) => {
                const url = new URL(request.url);
                if (url.searchParams.get("tool_version") === "version") {
                    return HttpResponse.json(buildResponse(overrides));
                }
                return HttpResponse.json({});
            }),
        );
    }

    beforeEach(() => {
        // I tried using the useConfig mock and this component seems to bypass that, it would be
        // better if it didn't. We shouldn't have to stub out an API request to get a particular config.
        server.use(
            http.get("/api/configuration", ({ response }) => {
                return response.untyped(
                    HttpResponse.json({
                        enable_tool_source_display: false,
                        object_store_allows_id_selection: false,
                    }),
                );
            }),
            http.untyped.get("/api/tools/tool_id/build", ({ request }) => {
                const url = new URL(request.url);
                if (url.searchParams.get("tool_version") === "version") {
                    return HttpResponse.json(buildResponse());
                }
                return HttpResponse.json({});
            }),
            http.untyped.get("/api/webhooks", () => {
                return HttpResponse.json([]);
            }),
            http.untyped.get("/api/tools/tool_id/citations", () => {
                return HttpResponse.json([]);
            }),
        );

        mountToolForm();
    });

    it("shows props", async () => {
        await flushPromises();
        const button = wrapper.find("[data-description='run tool button']");
        expect(button.attributes("data-title")).toBe("Run tool: tool_name (version)");
        const dropdown = wrapper.findAll(".dropdown-item");
        expect(dropdown.length).toBe(2);
        const noToolParametersAlert = wrapper.find("[data-description='no tool parameters']");
        expect(noToolParametersAlert.text()).toContain("This tool requires no input parameters and can be run as is.");
        const help = wrapper.find(".form-help");
        expect(help.text()).toBe("help_text");
        const creator = wrapper.find(".creative-work-creator");
        expect(creator.text()).toContain("FakeName FakeSurname");
    });

    it("adds the executed tool to recent tools", async () => {
        await flushPromises();
        wrapper.findComponent(FormDisplay).vm.$emit("onChange", {}, false);

        const button = wrapper.find("[data-description='run tool button']");
        await button.trigger("click");
        await flushPromises();

        expect(userStore.recentTools).toEqual(["tool_id"]);
    });

    it("preserves client-side validation errors on input change (does not wipe formConfig.errors when only validationInternal is set)", async () => {
        useBuildResponse({ errors: {} });
        mountToolForm();
        await flushPromises();

        const formDisplay = wrapper.findComponent(FormDisplay);
        // Simulate steady state: no backend errors, but a client-side validation error
        // raised by FormDisplay (e.g. a required field was cleared).
        await formDisplay.vm.$emit("onValidation", ["multi_required", "Please provide a value for this option."]);
        // First onChange sets formConfigInitialized; second is the one under test.
        await formDisplay.vm.$emit("onChange", { multi_required: null }, false);
        await formDisplay.vm.$emit("onChange", { multi_required: null }, false);

        // Should NOT have been assigned null — that would cascade through props.errors
        // and wipe the client-side validation error before it can render.
        expect(formDisplay.props("errors")).toEqual({});
    });

    it("still wipes formConfig.errors when there are actual backend errors to clear on input change", async () => {
        useBuildResponse({ errors: { multi_required: "Backend rejected this value." } });
        mountToolForm();
        await flushPromises();

        const formDisplay = wrapper.findComponent(FormDisplay);
        // First onChange sets formConfigInitialized; second triggers the wipe.
        await formDisplay.vm.$emit("onChange", { multi_required: "alpha" }, false);
        await formDisplay.vm.$emit("onChange", { multi_required: "alpha" }, false);

        expect(formDisplay.props("errors")).toBeNull();
    });

    function licenseAgreement(overrides = {}) {
        return {
            agreement_hash: "a".repeat(64),
            id: "test_license",
            version: "1",
            label: "Test License",
            url: null,
            affirmation: "I agree to the test license.",
            terms: "Test terms.",
            binds: "submission",
            accepted: false,
            ...overrides,
        };
    }

    async function affirmLicense(licenseId: string) {
        await wrapper.find(`input[data-test-id='license-affirm-${licenseId}-input']`).setChecked(true);
        await flushPromises();
    }

    it("blocks running until license agreements are affirmed and sends one-time acceptances", async () => {
        let submitted: Record<string, unknown> | undefined;
        server.use(
            http.untyped.post("/api/tools", async ({ request }) => {
                submitted = (await request.json()) as Record<string, unknown>;
                // Fail the submission so the form does not navigate away - only the payload matters here.
                return HttpResponse.json({ err_msg: "captured" }, { status: 400 });
            }),
        );
        useBuildResponse({ license_agreements: [licenseAgreement()] });
        mountToolForm();
        await flushPromises();
        wrapper.findComponent(FormDisplay).vm.$emit("onChange", {}, false);
        await flushPromises();

        const button = wrapper.find("[data-description='run tool button']");
        expect(button.classes()).toContain("g-disabled");
        expect(button.attributes("data-title")).toBe("Please accept all license agreements before running the tool.");
        expect(wrapper.text()).toContain("I agree to the test license.");
        expect(wrapper.find("input[data-test-id='license-remember-test_license-input']").exists()).toBe(false);

        await affirmLicense("test_license");
        expect(button.classes()).not.toContain("g-disabled");
        await button.trigger("click");
        await flushPromises();
        expect(submitted?.one_time_license_acceptances).toEqual(["a".repeat(64)]);
    });

    it("does not prompt for license agreements the user already accepts", async () => {
        useBuildResponse({ license_agreements: [licenseAgreement({ binds: "user", accepted: true })] });
        mountToolForm();
        await flushPromises();
        wrapper.findComponent(FormDisplay).vm.$emit("onChange", {}, false);
        await flushPromises();

        expect(wrapper.find("[data-description='license accepted']").exists()).toBe(true);
        expect(wrapper.find("[data-description='run tool button']").classes()).not.toContain("g-disabled");
    });

    it("accepts user-bound license agreements persistently when remembered", async () => {
        let accepted: Record<string, unknown> | undefined;
        let submitted: Record<string, unknown> | undefined;
        server.use(
            http.untyped.post("/api/users/current/license_acceptances", async ({ request }) => {
                accepted = (await request.json()) as Record<string, unknown>;
                return HttpResponse.json({});
            }),
            http.untyped.post("/api/tools", async ({ request }) => {
                submitted = (await request.json()) as Record<string, unknown>;
                return HttpResponse.json({ err_msg: "captured" }, { status: 400 });
            }),
        );
        useBuildResponse({ license_agreements: [licenseAgreement({ binds: "user" })] });
        mountToolForm();
        await flushPromises();
        wrapper.findComponent(FormDisplay).vm.$emit("onChange", {}, false);
        await flushPromises();

        const remember = wrapper.find("input[data-test-id='license-remember-test_license-input']");
        expect(remember.attributes("disabled")).toBeDefined();
        await affirmLicense("test_license");
        await remember.setChecked(true);
        await flushPromises();
        await wrapper.find("[data-description='run tool button']").trigger("click");
        await flushPromises();

        expect(accepted).toEqual({
            tool_id: "tool_id",
            tool_version: "version",
            license_id: "test_license",
            agreement_hash: "a".repeat(64),
        });
        // The job is authorized by the persistent acceptance, not a one-time one.
        expect(submitted).toBeDefined();
        expect(submitted?.one_time_license_acceptances).toBeUndefined();
    });

    it("does not submit when accepting a remembered license agreement fails", async () => {
        let submitted = false;
        server.use(
            http.untyped.post("/api/users/current/license_acceptances", () =>
                HttpResponse.json({ err_msg: "License agreement has changed." }, { status: 400 }),
            ),
            http.untyped.post("/api/tools", () => {
                submitted = true;
                return HttpResponse.json({ err_msg: "captured" }, { status: 400 });
            }),
        );
        useBuildResponse({ license_agreements: [licenseAgreement({ binds: "user" })] });
        mountToolForm();
        await flushPromises();
        wrapper.findComponent(FormDisplay).vm.$emit("onChange", {}, false);
        await flushPromises();

        await affirmLicense("test_license");
        await wrapper.find("input[data-test-id='license-remember-test_license-input']").setChecked(true);
        await flushPromises();
        await wrapper.find("[data-description='run tool button']").trigger("click");
        await flushPromises();

        expect(submitted).toBe(false);
        expect(wrapper.text()).toContain("License agreement has changed.");
        expect(wrapper.find("[data-description='run tool button']").classes()).not.toContain("g-disabled");
    });

    it("shows an error alert when tool submission returns an error message", async () => {
        const errorMessage = "New identifier [duplicate] appears twice in resulting collection.";
        server.use(
            http.untyped.post("/api/tools", () => {
                return HttpResponse.json({ err_msg: errorMessage }, { status: 400 });
            }),
        );
        await flushPromises();
        wrapper.findComponent(FormDisplay).vm.$emit("onChange", {}, false);

        const button = wrapper.find("[data-description='run tool button']");
        await button.trigger("click");
        await flushPromises();

        expect(wrapper.text()).toContain(errorMessage);
    });
});
