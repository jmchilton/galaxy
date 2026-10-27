import { getLocalVue } from "@tests/vitest/helpers";
import { mount, type VueWrapper } from "@vue/test-utils";
import flushPromises from "flush-promises";
import { afterEach, beforeEach, describe, expect, it } from "vitest";

import { useServerMock } from "@/api/client/__mocks__";
import type { ComparisonTable as Table } from "@/api/comparisons";

import STEP_RUNS from "./test-data/step_runs.json";

import ComparisonTable from "./ComparisonTable.vue";
import StepRunsTab from "./StepRunsTab.vue";

const TABLE = STEP_RUNS as unknown as Table;
const { server, http } = useServerMock();

let requests: { workflowId: string; query: URLSearchParams }[];
let total: string;
let fail: boolean;
let wrapper: VueWrapper | undefined;

beforeEach(() => {
    requests = [];
    total = String(TABLE.rows.length);
    fail = false;
    server.use(
        http.get("/api/workflows/{workflow_id}/step_runs", ({ request, params, response }) => {
            const query = new URL(request.url).searchParams;
            requests.push({ workflowId: String(params.workflow_id), query });
            if (fail) {
                return response("4XX").json({ err_msg: "Step label not found", err_code: 404 }, { status: 404 });
            }
            const metadata = query.getAll("metadata_elements");
            return response(200).json(
                { ...TABLE, query: { ...TABLE.query, metadata_elements: metadata } },
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

async function mountTab(props: Record<string, unknown> = {}) {
    const localVue = getLocalVue();
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
        expect(tab.find(".step-runs-summary").text()).toBe("Showing 1–6 of 60 · newest first · your runs only");
        const pagination = tab.find("[aria-label='Pages of runs']");
        expect(pagination.exists()).toBe(true);
        await pagination.find("[aria-posinset='3'], button[aria-label='Go to page 3']").trigger("click");
        await flushPromises();
        expect(requests.map((r) => r.query.get("offset"))).toEqual(["0", "50"]);
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

    it("shows the server's error", async () => {
        fail = true;
        const tab = await mountTab();
        expect(tab.find(".alert-danger").text()).toContain("Step label not found");
    });
});
