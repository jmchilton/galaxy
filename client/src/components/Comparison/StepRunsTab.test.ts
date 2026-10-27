import { getLocalVue } from "@tests/vitest/helpers";
import { mount, type VueWrapper } from "@vue/test-utils";
import flushPromises from "flush-promises";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { useServerMock } from "@/api/client/__mocks__";

import { seedDisplayPrefs, STEP_RUNS_TABLE } from "./test-utils";

import ComparisonTable from "./ComparisonTable.vue";
import StepRunsTab from "./StepRunsTab.vue";

const TABLE = STEP_RUNS_TABLE;
const STORED_WORKFLOW_ID = TABLE.query.kind === "step_runs" ? TABLE.query.workflow_id : "";
const { server, http } = useServerMock();

// Display preferences persist per user; use the real storage.
vi.unmock("@/composables/userLocalStorage");

let requests: { workflowId: string; query: URLSearchParams }[];
let total: string;
let fail: boolean;
let gate: Promise<void> | undefined;
let versionsAvailable: number[];
let wrapper: VueWrapper | undefined;

beforeEach(() => {
    localStorage.clear();
    requests = [];
    total = String(TABLE.rows.length);
    fail = false;
    gate = undefined;
    versionsAvailable = [0, 1];
    server.use(
        http.get("/api/workflows/{workflow_id}/step_runs", async ({ request, params, response }) => {
            const query = new URL(request.url).searchParams;
            requests.push({ workflowId: String(params.workflow_id), query });
            await gate;
            if (fail) {
                return response("4XX").json({ err_msg: "Step label not found", err_code: 404 }, { status: 404 });
            }
            const metadata = query.getAll("metadata_elements");
            return response(200).json(
                {
                    ...TABLE,
                    query: { ...TABLE.query, metadata_elements: metadata, offset: Number(query.get("offset")) },
                    versions_available: versionsAvailable,
                },
                {
                    headers: { total_matches: total },
                },
            );
        }),
    );
});

afterEach(() => {
    wrapper?.unmount();
    wrapper = undefined;
});

async function mountTab(props: Record<string, unknown> = {}, storedPrefs?: Record<string, unknown>) {
    const localVue = getLocalVue();
    if (storedPrefs) {
        seedDisplayPrefs(storedPrefs);
    }
    wrapper = mount(StepRunsTab as object, {
        props: {
            workflowId: "wf-instance",
            instance: true,
            stepLabel: "second_cat",
            currentInvocationId: "x",
            ...props,
        },
        global: {
            ...localVue,
            stubs: { ...localVue.stubs, ItemPopoverLink: true, ComparisonRowDetail: true },
        },
    });
    await flushPromises();
    return wrapper;
}

describe("StepRunsTab", () => {
    it("asks step_runs for the step label by workflow instance, newest page first", async () => {
        const tab = await mountTab();
        expect(requests).toHaveLength(1);
        const { workflowId, query } = requests[0]!;
        expect(workflowId).toBe("wf-instance");
        expect(query.get("step_label")).toBe("second_cat");
        expect(query.get("instance")).toBe("true");
        expect(query.get("offset")).toBe("0");
        expect(query.get("limit")).toBe("25");
        expect(tab.findComponent(ComparisonTable).props("table").rows).toHaveLength(TABLE.rows.length);
    });

    it("reads total_matches and pages with it", async () => {
        total = "60";
        const tab = await mountTab();
        expect(tab.find(".comparison-summary").text()).toBe("Showing 1–6 of 60 · newest first · your runs only");
        const pagination = tab.find("[aria-label='Pages of runs']");
        expect(pagination.exists()).toBe(true);
        await pagination.find("button[aria-label='Go to page 3']").trigger("click");
        await flushPromises();
        expect(requests.map((r) => r.query.get("offset"))).toEqual(["0", "50"]);
    });

    it("summarises the loaded page until the next one arrives", async () => {
        total = "60";
        const tab = await mountTab();
        let release: () => void = () => {};
        gate = new Promise((resolve) => (release = resolve));
        await tab.find("button[aria-label='Go to page 3']").trigger("click");
        await flushPromises();
        expect(requests).toHaveLength(2);
        expect(tab.find(".comparison-summary").text()).toBe("Showing 1–6 of 60 · newest first · your runs only");
        release();
        await flushPromises();
        expect(tab.find(".comparison-summary").text()).toBe("Showing 51–56 of 60 · newest first · your runs only");
    });

    it("drops the previous step's table and page link while another step loads", async () => {
        const tab = await mountTab();
        expect(tab.find("a.comparison-view-all").exists()).toBe(true);
        let release: () => void = () => {};
        gate = new Promise((resolve) => (release = resolve));
        await tab.setProps({ stepLabel: "first_cat" });
        await flushPromises();
        expect(requests.at(-1)!.query.get("step_label")).toBe("first_cat");
        expect(tab.findComponent(ComparisonTable).exists()).toBe(false);
        expect(tab.find("a.comparison-view-all").exists()).toBe(false);
        expect(tab.text()).toContain("Loading runs of this step");
        release();
        await flushPromises();
        expect(tab.findComponent(ComparisonTable).exists()).toBe(true);
    });

    it("links to the full page by the stored workflow id the server echoed", async () => {
        const tab = await mountTab();
        expect(tab.find("a.comparison-view-all").attributes("href")).toBe(
            "/comparisons?kind=step_runs&workflow_id=adb5f5c93f827949&step_label=second_cat",
        );
    });

    it("filters by state and workflow version from the first page, and links the page with them", async () => {
        total = "60";
        const tab = await mountTab();
        await tab.find("button[aria-label='Go to page 3']").trigger("click");
        await flushPromises();
        const versions = tab.findAll(".comparison-filter-versions input");
        expect(versions.map((input) => input.element.closest("label")!.textContent!.trim())).toEqual(["v1", "v2"]);
        await tab.find(".comparison-filter-versions input[value='1']").setValue(true);
        await flushPromises();
        await tab.find(".comparison-filter-states input[value='error']").setValue(true);
        await flushPromises();
        expect(requests).toHaveLength(4);
        const last = requests.at(-1)!.query;
        expect(last.getAll("versions")).toEqual(["1"]);
        expect(last.getAll("states")).toEqual(["error"]);
        expect(last.get("offset")).toBe("0");
        expect(tab.find("a.comparison-view-all").attributes("href")).toBe(
            "/comparisons?kind=step_runs&workflow_id=adb5f5c93f827949&step_label=second_cat&states=error&versions=1",
        );
    });

    it("offers no version filter for a step in one version", async () => {
        versionsAvailable = [1];
        const tab = await mountTab();
        expect(tab.find(".comparison-filter-states").exists()).toBe(true);
        expect(tab.find(".comparison-filter-versions").exists()).toBe(false);
    });

    it("hides pagination when one page holds every run", async () => {
        const tab = await mountTab();
        expect(tab.find("[aria-label='Pages of runs']").exists()).toBe(false);
    });

    it("refetches with the metadata element a column switches to", async () => {
        const tab = await mountTab();
        tab.findComponent(ComparisonTable).vm.$emit("update:columnDisplay", { "output:out_file1": "meta:data_lines" });
        await flushPromises();
        expect(requests).toHaveLength(2);
        expect(requests[1]!.query.getAll("metadata_elements")).toEqual(["data_lines"]);
        expect(requests[1]!.query.get("offset")).toBe("0");
    });

    it("applies stored display preferences of this step's label to the first request", async () => {
        const tab = await mountTab(
            { storedWorkflowId: STORED_WORKFLOW_ID },
            {
                [`step_runs:${STORED_WORKFLOW_ID}:second_cat`]: {
                    columnDisplay: { "output:out_file1": "meta:data_lines" },
                    transpose: true,
                },
                [`step_runs:${STORED_WORKFLOW_ID}:other_step`]: { columnDisplay: { "input:input1": "meta:dbkey" } },
                [`step_runs:another_workflow:second_cat`]: { hidden: ["state"] },
            },
        );
        expect(requests).toHaveLength(1);
        expect(requests[0]!.query.getAll("metadata_elements")).toEqual(["data_lines"]);
        const table = tab.findComponent(ComparisonTable);
        expect(table.props("transpose")).toBe(true);
        expect(table.props("visibleColumns")).toContain("state");
    });

    it("hides a column the chooser toggles", async () => {
        const tab = await mountTab();
        const table = tab.findComponent(ComparisonTable);
        expect(table.props("visibleColumns")).toContain("input:input1");
        table.vm.$emit("toggle-column", "input:input1");
        await flushPromises();
        expect(table.props("visibleColumns")).not.toContain("input:input1");
        table.vm.$emit("reset-columns");
        await flushPromises();
        expect(table.props("visibleColumns")).toContain("input:input1");
    });

    it("explains an unlabelled step and does not fetch", async () => {
        const tab = await mountTab({ stepLabel: undefined });
        expect(requests).toHaveLength(0);
        expect(tab.text()).toContain("Label this step to compare its runs");
        expect(tab.findComponent(ComparisonTable).exists()).toBe(false);
    });

    it("shows the server's error and retries it", async () => {
        fail = true;
        const tab = await mountTab();
        expect(tab.find(".alert-danger").text()).toContain("Step label not found");
        fail = false;
        await tab.find(".alert-danger .comparison-retry").trigger("click");
        await flushPromises();
        expect(requests).toHaveLength(2);
        expect(tab.find(".alert-danger").exists()).toBe(false);
        expect(tab.findComponent(ComparisonTable).exists()).toBe(true);
    });
});
