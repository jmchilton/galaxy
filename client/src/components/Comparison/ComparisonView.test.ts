import { createTestRouter, getLocalVue, withPlugins } from "@tests/vitest/helpers";
import { mount, type VueWrapper } from "@vue/test-utils";
import flushPromises from "flush-promises";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { HttpResponse, useServerMock } from "@/api/client/__mocks__";
import type { ComparisonTable as Table } from "@/api/comparisons";

import { seedDisplayPrefs, STEP_RUNS_TABLE } from "./test-utils";

import ComparisonPager from "./ComparisonPager.vue";
import ComparisonTable from "./ComparisonTable.vue";
import ComparisonView from "./ComparisonView.vue";

const STEP_TABLE = STEP_RUNS_TABLE;
const { server, http } = useServerMock();

// Display preferences persist per user; use the real storage.
vi.unmock("@/composables/userLocalStorage");

let requests: { path: string; query: URLSearchParams }[];
let fail: boolean;
// While set, tool_runs responses wait for it.
let toolRunsGate: Promise<void> | undefined;
let wrapper: VueWrapper | undefined;

function tableFor(query: Record<string, unknown>): Table {
    return { ...STEP_TABLE, query: { ...STEP_TABLE.query, ...query } as Table["query"] };
}

beforeEach(() => {
    localStorage.clear();
    requests = [];
    fail = false;
    toolRunsGate = undefined;
    const record = (request: Request) => {
        const url = new URL(request.url);
        requests.push({ path: url.pathname, query: url.searchParams });
        return url.searchParams;
    };
    server.use(
        http.get("/api/workflows/{workflow_id}/step_runs", ({ request, response }) => {
            record(request);
            return response(200).json(
                { ...STEP_TABLE, versions_available: [0, 1] },
                { headers: { total_matches: "60" } },
            );
        }),
        http.get("/api/workflows/{workflow_id}/output_runs", ({ request, response }) => {
            const query = record(request);
            const table = {
                ...tableFor({ kind: "output_runs", output_labels: query.getAll("output_labels") }),
                output_labels_available: ["a", "b"],
                versions_available: [0, 1],
            };
            return response(200).json(table, { headers: { total_matches: "6" } });
        }),
        http.get("/api/tool_runs", async ({ request, response }) => {
            const query = record(request);
            await toolRunsGate;
            if (fail) {
                return response("5XX").json({ err_msg: "Server down", err_code: 500 }, { status: 500 });
            }
            const table = {
                ...tableFor({ kind: "tool_runs", tool_id: query.get("tool_id") }),
                tool_versions_available: ["1.0", "2.0"],
            };
            return response(200).json(table, { headers: { total_matches: "6" } });
        }),
        http.get("/api/workflows/{workflow_id}", ({ response }) => {
            return response(200).json({ name: "Two cats" } as never);
        }),
        // Tool Shed ids hold slashes, so match any path under /api/tools/.
        http.untyped.get("/api/tools/*", () => HttpResponse.json({ id: "cat1", name: "Concatenate" })),
    );
});

afterEach(() => {
    wrapper?.unmount();
    wrapper = undefined;
});

async function mountView(query: Record<string, string | string[]>, storedPrefs?: Record<string, unknown>) {
    const router = createTestRouter();
    const replace = vi.spyOn(router, "replace").mockResolvedValue(undefined);
    const localVue = getLocalVue();
    if (storedPrefs) {
        seedDisplayPrefs(storedPrefs);
    }
    wrapper = mount(ComparisonView as object, {
        props: { query },
        global: { ...withPlugins(localVue, router), stubs: { ...localVue.stubs, ComparisonTable: true } },
    });
    await flushPromises();
    return { view: wrapper, replace };
}

function comparisonRequests() {
    return requests.filter((r) => /_runs$/.test(r.path));
}

describe("ComparisonView", () => {
    it("forwards a step_runs query unchanged, repeating list values", async () => {
        const { view } = await mountView({
            kind: "step_runs",
            workflow_id: "wf1",
            step_label: "second_cat",
            states: ["ok", "error"],
            offset: "25",
            sort_by: "update_time",
        });
        const [only, ...rest] = comparisonRequests();
        expect(rest).toHaveLength(0);
        expect(only!.path).toBe("/api/workflows/wf1/step_runs");
        expect(only!.query.get("step_label")).toBe("second_cat");
        expect(only!.query.getAll("states")).toEqual(["ok", "error"]);
        expect(only!.query.get("offset")).toBe("25");
        expect(only!.query.get("sort_by")).toBe("update_time");
        expect(only!.query.has("kind")).toBe(false);
        expect(view.findComponent(ComparisonTable).exists()).toBe(true);
        expect(view.find(".breadcrumb-heading").text()).toContain('Runs of step "second_cat"');
        expect(view.find(".breadcrumb-heading").text()).toContain("Two cats");
    });

    it("forwards output labels without splitting on commas", async () => {
        await mountView({ kind: "output_runs", workflow_id: "wf1", output_labels: ["a,b", "n"] });
        const [only] = comparisonRequests();
        expect(only!.path).toBe("/api/workflows/wf1/output_runs");
        expect(only!.query.getAll("output_labels")).toEqual(["a,b", "n"]);
    });

    it("forwards a tool_runs query and offers the tool versions the server found", async () => {
        const { view } = await mountView({
            kind: "tool_runs",
            tool_id: "toolshed.g2.bx.psu.edu/repos/devteam/cat/cat1/1.0",
            tool_versions: "1.0",
            include_workflow_jobs: "false",
            history_id: "h1",
        });
        const [only] = comparisonRequests();
        expect(only!.path).toBe("/api/tool_runs");
        expect(only!.query.get("tool_id")).toBe("toolshed.g2.bx.psu.edu/repos/devteam/cat/cat1/1.0");
        expect(only!.query.getAll("tool_versions")).toEqual(["1.0"]);
        expect(only!.query.get("include_workflow_jobs")).toBe("false");
        expect(only!.query.get("history_id")).toBe("h1");
        const versions = view.find(".comparison-filter-tool-versions");
        expect(versions.findAll("input").map((input) => input.attributes("value"))).toEqual(["1.0", "2.0"]);
        expect(view.find(".comparison-filter-history").exists()).toBe(true);
        expect(view.find(".breadcrumb-heading").text()).toContain("Runs of Concatenate");
    });

    it("applies stored display preferences named by the URL to the first request", async () => {
        await mountView(
            { kind: "tool_runs", tool_id: "cat1" },
            {
                "tool_runs:cat1": { columnDisplay: { "output:out_file1": "meta:data_lines" } },
                "tool_runs:cat2": { columnDisplay: { "input:input1": "meta:dbkey" } },
            },
        );
        const [only, ...rest] = comparisonRequests();
        expect(rest).toHaveLength(0);
        expect(only!.query.getAll("metadata_elements")).toEqual(["data_lines"]);
    });

    it("keys stored display preferences by the versionless Tool Shed id", async () => {
        await mountView(
            { kind: "tool_runs", tool_id: "toolshed.g2.bx.psu.edu/repos/devteam/cat/cat1/2.0" },
            {
                "tool_runs:toolshed.g2.bx.psu.edu/repos/devteam/cat/cat1": {
                    columnDisplay: { "output:out_file1": "meta:data_lines" },
                },
            },
        );
        const [only, ...rest] = comparisonRequests();
        expect(rest).toHaveLength(0);
        expect(only!.query.getAll("metadata_elements")).toEqual(["data_lines"]);
    });

    it("offers every output label the server reports, not only the selected ones", async () => {
        const { view } = await mountView({ kind: "output_runs", workflow_id: "wf1", output_labels: "a" });
        const outputs = view.find(".comparison-filter-outputs");
        expect(outputs.findAll("input").map((input) => input.attributes("value"))).toEqual(["a", "b"]);
    });

    it("drops the old table when the URL names another comparison", async () => {
        const { view } = await mountView({ kind: "tool_runs", tool_id: "cat1" });
        expect(view.findComponent(ComparisonTable).exists()).toBe(true);
        let release: () => void = () => {};
        toolRunsGate = new Promise((resolve) => (release = resolve));
        await view.setProps({ query: { kind: "tool_runs", tool_id: "cat2" } });
        await flushPromises();
        expect(view.findComponent(ComparisonTable).exists()).toBe(false);
        expect(view.text()).toContain("Loading runs");
        release();
        await flushPromises();
        expect(view.findComponent(ComparisonTable).props("table").query).toMatchObject({ tool_id: "cat2" });
    });

    it("keeps the table while only filters change", async () => {
        const { view } = await mountView({ kind: "tool_runs", tool_id: "cat1" });
        let release: () => void = () => {};
        toolRunsGate = new Promise((resolve) => (release = resolve));
        await view.setProps({ query: { kind: "tool_runs", tool_id: "cat1", states: "ok" } });
        await flushPromises();
        expect(view.findComponent(ComparisonTable).exists()).toBe(true);
        release();
        await flushPromises();
    });

    it("names the workflow of the current URL when an older name request resolves last", async () => {
        const releases: Record<string, () => void> = {};
        server.use(
            http.get("/api/workflows/{workflow_id}", async ({ params, response }) => {
                const workflowId = String(params.workflow_id);
                await new Promise<void>((resolve) => (releases[workflowId] = resolve));
                return response(200).json({ name: `Workflow ${workflowId}` } as never);
            }),
        );
        const { view } = await mountView({ kind: "output_runs", workflow_id: "wfA" });
        await view.setProps({ query: { kind: "output_runs", workflow_id: "wfB" } });
        await flushPromises();
        releases.wfB!();
        await flushPromises();
        releases.wfA!();
        await flushPromises();
        const heading = view.find(".breadcrumb-heading").text();
        expect(heading).toContain("Workflow wfB");
        expect(heading).not.toContain("Workflow wfA");
    });

    it("describes the loaded sort order", async () => {
        const { view } = await mountView({ kind: "tool_runs", tool_id: "cat1" });
        expect(view.findComponent(ComparisonPager).props()).toMatchObject({ sortBy: "create_time", sortDesc: true });
    });

    it("retries a failed fetch", async () => {
        fail = true;
        const { view } = await mountView({ kind: "tool_runs", tool_id: "cat1" });
        expect(view.find(".alert-danger").text()).toContain("Server down");
        fail = false;
        await view.find(".alert-danger .comparison-retry").trigger("click");
        await flushPromises();
        expect(comparisonRequests()).toHaveLength(2);
        expect(view.find(".alert-danger").exists()).toBe(false);
        expect(view.findComponent(ComparisonTable).exists()).toBe(true);
    });

    it.each([
        [{ kind: "nope" }, 'Unknown comparison kind "nope".'],
        [{ kind: "toString" }, 'Unknown comparison kind "toString".'],
        [{ kind: "__proto__" }, 'Unknown comparison kind "__proto__".'],
        [{}, "No comparison kind given."],
        [{ kind: "step_runs", workflow_id: "wf1" }, "A step_runs comparison needs step_label."],
        [{ kind: "tool_runs", tool_id: "cat1", state: "ok" }, "A tool_runs comparison does not take state."],
        [
            { kind: "tool_runs", tool_id: "cat1", output_labels: "a", constructor: "x" },
            "A tool_runs comparison does not take output_labels, constructor.",
        ],
    ])("shows an error and fetches nothing for %j", async (query, message) => {
        const { view } = await mountView(query);
        expect(comparisonRequests()).toHaveLength(0);
        expect(view.find(".alert-danger").text()).toBe(message);
    });

    it("labels state filters as the State column does, keeping raw values", async () => {
        const { view } = await mountView({ kind: "step_runs", workflow_id: "wf1", step_label: "s" });
        const error = view.find(".comparison-filter-states input[value='error']");
        expect(error.element.closest("label")!.textContent!.trim()).toBe("failed");
    });

    it("writes a state filter to the URL and returns to the first page", async () => {
        const { view, replace } = await mountView({
            kind: "step_runs",
            workflow_id: "wf1",
            step_label: "second_cat",
            offset: "25",
        });
        await view.find(".comparison-filter-states input[value='error']").setValue(true);
        expect(replace).toHaveBeenLastCalledWith({
            query: { kind: "step_runs", workflow_id: "wf1", step_label: "second_cat", states: ["error"] },
        });
    });

    it.each<Record<string, string>>([{ kind: "step_runs", step_label: "second_cat" }, { kind: "output_runs" }])(
        "offers the workflow versions of $kind and writes the filter to the URL",
        async (base) => {
            const { view, replace } = await mountView({ ...base, workflow_id: "wf1", versions: "0" });
            expect(comparisonRequests()[0]!.query.getAll("versions")).toEqual(["0"]);
            const versions = view.findAll(".comparison-filter-versions input");
            expect(
                versions.map((input) => [input.attributes("value"), (input.element as HTMLInputElement).checked]),
            ).toEqual([
                ["0", true],
                ["1", false],
            ]);
            await view.find(".comparison-filter-versions input[value='1']").setValue(true);
            expect(replace).toHaveBeenLastCalledWith({
                query: { ...base, workflow_id: "wf1", versions: ["0", "1"] },
            });
        },
    );

    it("writes paging and page size to the URL", async () => {
        const { view, replace } = await mountView({ kind: "step_runs", workflow_id: "wf1", step_label: "s" });
        view.findComponent(ComparisonPager).vm.$emit("update:offset", 50);
        expect(replace).toHaveBeenLastCalledWith({
            query: { kind: "step_runs", workflow_id: "wf1", step_label: "s", offset: "50" },
        });
        await view.find("#comparison-page-size").setValue("50");
        expect(replace).toHaveBeenLastCalledWith({
            query: { kind: "step_runs", workflow_id: "wf1", step_label: "s", limit: "50" },
        });
    });

    it("writes include_workflow_jobs=false when runs inside workflows are excluded", async () => {
        const { view, replace } = await mountView({ kind: "tool_runs", tool_id: "cat1" });
        await view.find(".comparison-filter-workflow-jobs input").setValue(false);
        expect(replace).toHaveBeenLastCalledWith({
            query: { kind: "tool_runs", tool_id: "cat1", include_workflow_jobs: "false" },
        });
    });
});
