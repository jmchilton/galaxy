import "@tests/vitest/mockHelpPopovers";

import { getFakeRegisteredUser } from "@tests/test-data";
import { getLocalVue, injectTestRouter } from "@tests/vitest/helpers";
import { mount, type VueWrapper } from "@vue/test-utils";
import flushPromises from "flush-promises";
import { createPinia } from "pinia";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { HttpResponse, useServerMock } from "@/api/client/__mocks__";
import type { AnyHistory } from "@/api/index.js";
import MockCurrentHistory from "@/components/providers/MockCurrentHistory";
import { useToast } from "@/composables/toast";
import { useHistoryStore } from "@/stores/historyStore";
import { useUserStore } from "@/stores/userStore";

import ToolCard from "./ToolCard.vue";
import ToolForm from "./ToolForm.vue";
import FormDisplay from "@/components/Form/FormDisplay.vue";
import FormElement from "@/components/Form/FormElement.vue";

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
    let wrapper: VueWrapper;
    let userStore: ReturnType<typeof useUserStore>;
    let historyStore: ReturnType<typeof useHistoryStore>;

    function mountToolForm(props = {}) {
        wrapper = mount(ToolForm as object, {
            propsData: {
                id: "tool_id",
                version: "version",
                ...props,
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

    describe("job count", () => {
        const RUN_BUTTON = "[data-description='run tool button']";
        const twelveJobs = {
            job_count: 12,
            reason: null,
            inputs: [{ name: "input1", count: 12, linked: true }],
        };

        function respondToBuilds(...responses: Array<{ body: object; gate?: Promise<void> }>) {
            let call = 0;
            server.use(
                http.untyped.post("/api/tools/tool_id/build", async () => {
                    const { body, gate } = responses[Math.min(call++, responses.length - 1)]!;
                    await gate;
                    return HttpResponse.json(buildResponse(body));
                }),
            );
        }

        async function requestUpdate() {
            wrapper.findComponent(FormDisplay).vm.$emit("onChange", {}, true);
            await flushPromises();
        }

        function jobCountText() {
            const jobCount = wrapper.find(".tool-form-job-count");
            expect(jobCount.exists()).toBe(true);
            return jobCount.text();
        }

        const runButton = () => wrapper.find(RUN_BUTTON);

        function runButtonTitle() {
            return runButton().attributes("data-title");
        }

        it("shows the count from the build response and clears it once nothing is batched", async () => {
            respondToBuilds({ body: { job_expansion: twelveJobs } }, { body: {} });
            await flushPromises();

            await requestUpdate();
            expect(jobCountText()).toContain("This will run 12 jobs.");
            expect(runButtonTitle()).toBe("Run tool: tool_name (version) - 12 jobs");

            await requestUpdate();
            expect(jobCountText()).toBe("");
            expect(runButtonTitle()).toBe("Run tool: tool_name (version)");
        });

        it("ignores a build response that arrives after a newer one", async () => {
            let releaseStale!: () => void;
            const stale = new Promise<void>((resolve) => (releaseStale = resolve));
            respondToBuilds({ body: { version: "stale", job_expansion: twelveJobs }, gate: stale }, { body: {} });
            await flushPromises();

            const formDisplay = wrapper.findComponent(FormDisplay);
            formDisplay.vm.$emit("onChange", {}, true);
            formDisplay.vm.$emit("onChange", {}, true);
            await flushPromises();
            expect(wrapper.findComponent(ToolCard).props("disabled")).toBe(false);

            releaseStale();
            await flushPromises();
            expect(runButtonTitle()).toBe("Run tool: tool_name (version)");
            expect(jobCountText()).toBe("");
        });

        it("leaves a size mismatch to client-side validation when it flags a batch input", async () => {
            const mismatch = {
                job_count: null,
                reason: "batch_mismatch",
                inputs: [
                    { name: "input1", count: 2, linked: true },
                    { name: "input2", count: 3, linked: true },
                ],
            };
            respondToBuilds({ body: { job_expansion: mismatch } });
            await flushPromises();

            await requestUpdate();
            const warning = wrapper.find("[data-job-count-notice='mismatch']");
            expect(warning.exists()).toBe(true);
            expect(warning.attributes("role")).toBe("alert");
            expect(warning.text()).toBe("Batch inputs must have matching sizes: input1 (2), input2 (3).");

            const formDisplay = wrapper.findComponent(FormDisplay);
            await formDisplay.vm.$emit("onValidation", ["other_param", "Please provide a value for this option."]);
            expect(jobCountText()).toContain("Batch inputs must have matching sizes");

            await formDisplay.vm.$emit("onValidation", ["input2", "Please make sure..."]);
            expect(jobCountText()).toBe("");
        });

        it("disables Run with the reason only when the server says the request cannot run", async () => {
            const empty = { job_count: 0, reason: null, inputs: [{ name: "input1", count: 0, linked: true }] };
            const mismatch = {
                job_count: null,
                reason: "batch_mismatch",
                inputs: [
                    { name: "input1", count: 3, linked: true },
                    { name: "input2", count: 3, linked: true },
                ],
            };
            respondToBuilds(
                { body: { job_expansion: empty } },
                { body: { job_expansion: mismatch } },
                { body: { job_expansion: twelveJobs } },
            );
            await flushPromises();

            await requestUpdate();
            expect(runButton().attributes("aria-disabled")).toBeUndefined();
            expect(jobCountText()).toContain("No jobs will run because a batch input is empty");

            await requestUpdate();
            expect(runButton().attributes("aria-disabled")).toBe("true");
            expect(runButtonTitle()).toBe("Batch inputs must match before the tool can run.");

            await requestUpdate();
            expect(runButton().attributes("aria-disabled")).toBeUndefined();
            expect(runButtonTitle()).toBe("Run tool: tool_name (version) - 12 jobs");
        });

        it("drops a blocking preview once a non-refreshing change edits a batched input", async () => {
            const mismatch = {
                job_count: null,
                reason: "batch_mismatch",
                inputs: [
                    { name: "input1", count: 3, linked: true },
                    { name: "cond|input2", count: 2, linked: true },
                ],
            };
            respondToBuilds({ body: { job_expansion: mismatch } });
            await flushPromises();
            const batch = (ids: string[]) => ({
                batch: true,
                product: false,
                values: ids.map((id) => ({ id, src: "hdca" })),
            });
            const formDisplay = wrapper.findComponent(FormDisplay);

            formDisplay.vm.$emit("onChange", { input1: batch(["a"]), "cond|input2": batch(["b"]) }, true);
            await flushPromises();
            expect(runButton().attributes("aria-disabled")).toBe("true");

            // Switching a conditional to a branch without the input doesn't rebuild the form.
            formDisplay.vm.$emit("onChange", { input1: batch(["a"]) }, false);
            await flushPromises();
            expect(runButton().attributes("aria-disabled")).toBeUndefined();
            expect(runButtonTitle()).toBe("Run tool: tool_name (version)");
        });

        it("disables Run when remapping a job onto more than one job", async () => {
            server.use(
                http.untyped.get("/api/jobs/job_id/build_for_rerun", () =>
                    HttpResponse.json(buildResponse({ job_remap: true, job_expansion: twelveJobs })),
                ),
            );
            mountToolForm({ jobId: "job_id" });
            await flushPromises();
            expect(runButton().attributes("aria-disabled")).toBeUndefined();
            expect(runButtonTitle()).toBe("Run tool: tool_name (version) - 12 jobs");

            const remap = wrapper.findAllComponents(FormElement).find((e) => e.props("id") === "rerun_remap_job_id");
            remap!.vm.$emit("input", true);
            await flushPromises();
            expect(runButton().attributes("aria-disabled")).toBe("true");
            expect(runButtonTitle()).toBe("Remapping replaces a single job, but this request would run several jobs.");
            expect(wrapper.find("[data-job-count-notice='remap']").exists()).toBe(true);
        });

        it("drops a blocking preview from the tool load once a non-refreshing change edits a batched input", async () => {
            const mismatch = {
                job_count: null,
                reason: "batch_mismatch",
                inputs: [
                    { name: "input1", count: 3, linked: true },
                    { name: "cond|input2", count: 2, linked: true },
                ],
            };
            useBuildResponse({ job_expansion: mismatch });
            mountToolForm();
            await flushPromises();
            const batch = (ids: string[]) => ({
                batch: true,
                product: false,
                values: ids.map((id) => ({ id, src: "hdca" })),
            });
            const formDisplay = wrapper.findComponent(FormDisplay);

            // The form reports the loaded values without asking for a rebuild.
            formDisplay.vm.$emit("onChange", { input1: batch(["a"]), "cond|input2": batch(["b"]) }, false);
            await flushPromises();
            expect(runButton().attributes("aria-disabled")).toBe("true");

            formDisplay.vm.$emit("onChange", { input1: batch(["a"]) }, false);
            await flushPromises();
            expect(runButton().attributes("aria-disabled")).toBeUndefined();
        });

        it("drops a blocking preview once a later update fails", async () => {
            const mismatch = {
                job_count: null,
                reason: "batch_mismatch",
                inputs: [
                    { name: "input1", count: 2, linked: true },
                    { name: "input2", count: 3, linked: true },
                ],
            };
            let fail = false;
            server.use(
                http.untyped.post("/api/tools/tool_id/build", () =>
                    fail
                        ? HttpResponse.json({ err_msg: "Rate limit exceeded" }, { status: 429 })
                        : HttpResponse.json(buildResponse({ job_expansion: mismatch })),
                ),
            );
            await flushPromises();

            await requestUpdate();
            expect(runButton().attributes("aria-disabled")).toBe("true");

            fail = true;
            await requestUpdate();
            expect(runButton().attributes("aria-disabled")).toBeUndefined();
            expect(runButtonTitle()).toBe("Run tool: tool_name (version)");
            expect(jobCountText()).toBe("");
            useToast().clearToasts();
        });

        it("keeps the newest tool version when an older version request finishes last", async () => {
            let releaseStale!: () => void;
            const stale = new Promise<void>((resolve) => (releaseStale = resolve));
            server.use(
                http.untyped.get("/api/tools/tool_id/build", async ({ request }) => {
                    const version = new URL(request.url).searchParams.get("tool_version");
                    if (version === "slow") {
                        await stale;
                    }
                    return HttpResponse.json(buildResponse({ version }));
                }),
            );
            await flushPromises();

            const toolCard = wrapper.findComponent(ToolCard);
            toolCard.vm.$emit("onChangeVersion", "slow");
            toolCard.vm.$emit("onChangeVersion", "fast");
            await flushPromises();
            expect(toolCard.props("version")).toBe("fast");

            releaseStale();
            await flushPromises();
            expect(toolCard.props("version")).toBe("fast");
            expect(toolCard.props("disabled")).toBe(false);
        });
    });

    it("reports a rejected form update and re-enables the form", async () => {
        const { toasts, clearToasts } = useToast();
        clearToasts();
        server.use(
            http.untyped.post("/api/tools/tool_id/build", () => {
                return HttpResponse.json({ err_msg: "Rate limit exceeded" }, { status: 429 });
            }),
        );
        await flushPromises();

        wrapper.findComponent(FormDisplay).vm.$emit("onChange", {}, true);
        await flushPromises();

        expect(toasts.value).toEqual([
            expect.objectContaining({
                message: "Rate limit exceeded",
                title: "Updating parameters failed",
                variant: "danger",
            }),
        ]);
        expect(wrapper.findComponent(ToolCard).props("disabled")).toBe(false);
        clearToasts();
    });
});
