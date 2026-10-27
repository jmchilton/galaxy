import { getLocalVue } from "@tests/vitest/helpers";
import { mount } from "@vue/test-utils";
import { describe, expect, it } from "vitest";

import type { ComparisonQuery, ComparisonRow, ComparisonTable } from "@/api/comparisons";

import STEP_RUNS from "./test-data/step_runs.json";

import ComparisonRowDetail from "./ComparisonRowDetail.vue";

const TABLE = STEP_RUNS as unknown as ComparisonTable;
const JOB_TABS_STUB = { name: "JobDetailsTabs", props: ["jobId"], template: "<div />" };
const BATCH_STUB = {
    name: "ToolExecutionJobs",
    props: ["implicitCollectionJobsId", "initialJobId"],
    template: "<div />",
};
const ITEM_STUB = { name: "GenericHistoryItem", props: ["itemId", "itemSrc"], template: "<div />" };

function mountDetail(row: ComparisonRow, query: ComparisonQuery = TABLE.query) {
    const localVue = getLocalVue();
    return mount(ComparisonRowDetail as object, {
        props: { row, columns: TABLE.columns, query },
        global: {
            ...localVue,
            stubs: {
                ...localVue.stubs,
                JobDetailsTabs: JOB_TABS_STUB,
                ToolExecutionJobs: BATCH_STUB,
                GenericHistoryItem: ITEM_STUB,
            },
        },
    });
}

function alertText(wrapper: ReturnType<typeof mountDetail>) {
    return wrapper.find(".comparison-row-detail-message").text().replace(/\s+/g, " ").trim();
}

describe("ComparisonRowDetail", () => {
    it("shows the output history items and the step job", () => {
        const row = TABLE.rows[1]!;
        const wrapper = mountDetail(row);
        const items = wrapper.findAllComponents(ITEM_STUB);
        expect(items.map((i) => [i.props("itemId"), i.props("itemSrc")])).toEqual([
            [(row.cells["output:out_file1"] as { id: string }).id, "hda"],
        ]);
        expect(wrapper.findComponent(JOB_TABS_STUB).props("jobId")).toBe(row.step_job!.id);
    });

    it("pages through a mapped step's jobs, from its first", () => {
        const row = TABLE.rows[4]!;
        const wrapper = mountDetail(row);
        expect(wrapper.findComponent(JOB_TABS_STUB).exists()).toBe(false);
        const batch = wrapper.findComponent(BATCH_STUB);
        expect(batch.props("implicitCollectionJobsId")).toBe(row.step_job!.id);
        expect(batch.props("initialJobId")).toBe("cb227cec8ca83994");
        expect(wrapper.text()).toContain("3 jobs");
        expect(wrapper.findComponent(ITEM_STUB).props("itemSrc")).toBe("hdca");
    });

    it("explains a step that has not run yet", () => {
        const wrapper = mountDetail(TABLE.rows[0]!);
        expect(wrapper.findComponent(JOB_TABS_STUB).exists()).toBe(false);
        expect(wrapper.text()).toContain("no job for this step yet");
        expect(wrapper.text()).toContain("No outputs.");
    });

    it("links a subworkflow step to the subworkflow run", () => {
        const row = { ...TABLE.rows[0]!, state: "scheduled", subworkflow_invocation_id: "sub1" };
        const wrapper = mountDetail(row);
        expect(wrapper.findComponent(JOB_TABS_STUB).exists()).toBe(false);
        expect(wrapper.text()).toContain("This step ran a subworkflow.");
        expect(wrapper.find("a.comparison-row-detail-subworkflow").attributes("href")).toBe(
            "/workflows/invocations/sub1",
        );
    });

    it("explains a step the run ended before reaching", () => {
        const row = { ...TABLE.rows[0]!, run: { ...TABLE.rows[0]!.run, state: "failed" } } as ComparisonRow;
        const wrapper = mountDetail(row);
        expect(alertText(wrapper)).toBe("This run ended before reaching this step.");
    });

    it("explains a step mapped over an empty collection", () => {
        const step_job = {
            model: "ImplicitCollectionJobs",
            id: "icj1",
            populated_state: "ok",
            states: {},
            representative_job_id: null,
            job_count: 0,
        } as const;
        const row = { ...TABLE.rows[0]!, state: "ok", step_job, step_type: "tool" } as ComparisonRow;
        const wrapper = mountDetail(row);
        expect(wrapper.findComponent(JOB_TABS_STUB).exists()).toBe(false);
        expect(wrapper.text()).not.toContain("Job 1 of 0");
        expect(alertText(wrapper)).toBe("Mapped over an empty collection: no jobs ran.");
    });

    it.each([
        ["ready", null, "Waiting for review: the run is paused at this step."],
        ["scheduled", true, "Reviewed: the run continued past this pause."],
        ["cancelled", false, "Review rejected: the run was cancelled at this pause."],
        ["cancelled", null, "This pause step was not reviewed before the run ended."],
    ])("explains a pause step in a %s run with action %s", (runState, action, message) => {
        const base = TABLE.rows[0]!;
        const row = {
            ...base,
            run: { ...base.run, state: runState },
            state: "scheduled",
            step_type: "pause",
            step_action: action,
        } as ComparisonRow;
        expect(alertText(mountDetail(row))).toBe(message);
    });

    it.each(["data_input", "parameter_input"])("explains a %s step has no job", (stepType) => {
        const row = { ...TABLE.rows[0]!, state: "scheduled", step_type: stepType } as ComparisonRow;
        expect(alertText(mountDetail(row))).toBe("Input steps run without a job.");
    });

    it("has no single job for a workflow-outputs row", () => {
        const query = { kind: "output_runs", workflow_id: "w" } as ComparisonQuery;
        const row = { ...TABLE.rows[1]!, step_job: null };
        const wrapper = mountDetail(row, query);
        expect(wrapper.findComponent(JOB_TABS_STUB).exists()).toBe(false);
        expect(wrapper.text()).toContain("no single job");
    });
});
