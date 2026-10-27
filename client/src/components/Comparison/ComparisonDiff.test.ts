import { getLocalVue } from "@tests/vitest/helpers";
import { mount } from "@vue/test-utils";
import { describe, expect, it } from "vitest";

import type { ComparisonRow, ComparisonTable } from "@/api/comparisons";

import STEP_RUNS from "./test-data/step_runs.json";

import ComparisonDiff from "./ComparisonDiff.vue";

const TABLE = STEP_RUNS as unknown as ComparisonTable;
const [NOT_RUN, V2_RUN, V1_RUN] = TABLE.rows as [ComparisonRow, ComparisonRow, ComparisonRow];
const MAPPED = TABLE.rows[4]!;
const LINKS = { "input:input1": "link", "output:out_file1": "link" } as const;
const PARAMS_STUB = {
    name: "JobParametersDiff",
    props: ["jobIdA", "jobIdB", "labelA", "labelB", "onlyDifferences"],
    template: "<div />",
};
const LINK_STUB = { name: "ItemPopoverLink", props: ["itemId", "itemSrc", "to"], template: "<a><slot /></a>" };

function mountDiff(rows: [ComparisonRow, ComparisonRow], props: Record<string, unknown> = {}) {
    const localVue = getLocalVue();
    return mount(ComparisonDiff as object, {
        props: { rows, columns: TABLE.columns, query: TABLE.query, displays: LINKS, ...props },
        global: {
            ...localVue,
            stubs: { ...localVue.stubs, JobParametersDiff: PARAMS_STUB, ItemPopoverLink: LINK_STUB },
        },
    });
}

function lineKeys(wrapper: ReturnType<typeof mountDiff>) {
    return wrapper.findAll("tbody tr").map((tr) => [tr.attributes("data-diff-key"), tr.classes().at(-1)]);
}

describe("ComparisonDiff", () => {
    it("shows only the fields that differ, plus outputs it can't compare by name", () => {
        const wrapper = mountDiff([V2_RUN, V1_RUN]);
        expect(lineKeys(wrapper)).toEqual([
            ["version", "comparison-diff-differs"],
            ["input:input1", "comparison-diff-differs"],
            ["output:out_file1", "comparison-diff-uncompared"],
        ]);
        expect(wrapper.find(".comparison-diff-summary").text()).toBe("2 of 6 fields differ");
        const version = wrapper.find("tr[data-diff-key='version']").findAll("td");
        expect(version.map((td) => td.text())).toEqual(["v2", "v1"]);
    });

    it("shows every field when not limited to differences", async () => {
        const wrapper = mountDiff([V2_RUN, V1_RUN]);
        await wrapper.find(".comparison-diff-only input").setValue(false);
        expect(lineKeys(wrapper).map(([key]) => key)).toEqual([
            "version",
            "state",
            "reused",
            "history",
            "input:input1",
            "output:out_file1",
        ]);
        expect(wrapper.findComponent(PARAMS_STUB).props("onlyDifferences")).toBe(false);
    });

    it("compares by each column's display", () => {
        const wrapper = mountDiff([V2_RUN, V1_RUN], {
            displays: { ...LINKS, "output:out_file1": "meta:data_lines" },
            requestedMetadata: ["data_lines"],
        });
        expect(wrapper.find("tr[data-diff-key='output:out_file1']").exists()).toBe(false);
    });

    it("diffs the two jobs' parameters", () => {
        const params = mountDiff([V2_RUN, V1_RUN]).findComponent(PARAMS_STUB);
        expect(params.props("jobIdA")).toBe(V2_RUN.step_job!.id);
        expect(params.props("jobIdB")).toBe(V1_RUN.step_job!.id);
        expect(params.props("onlyDifferences")).toBe(true);
    });

    it("compares a batch by its first job, and says so", () => {
        const wrapper = mountDiff([V2_RUN, MAPPED]);
        const ref = MAPPED.step_job as { representative_job_id: string };
        expect(wrapper.findComponent(PARAMS_STUB).props("jobIdB")).toBe(ref.representative_job_id);
        expect(wrapper.find(".comparison-diff-batch").text()).toBe("Run B is a batch of 3 jobs: job 1 shown.");
    });

    it("explains why parameters can't be compared when a run has no job", () => {
        const wrapper = mountDiff([NOT_RUN, V2_RUN]);
        expect(wrapper.findComponent(PARAMS_STUB).exists()).toBe(false);
        expect(wrapper.find(".comparison-diff-no-job").text()).toContain(
            "Run A: This run has no job for this step yet.",
        );
    });

    it("explains that workflow runs have no job", () => {
        const wrapper = mountDiff([V2_RUN, V1_RUN], { query: { ...TABLE.query, kind: "output_runs" } });
        expect(wrapper.findComponent(PARAMS_STUB).exists()).toBe(false);
        expect(wrapper.text()).toContain("A workflow run has no single job.");
    });

    it("emits close", async () => {
        const wrapper = mountDiff([V2_RUN, V1_RUN]);
        await wrapper.find(".comparison-diff-close").trigger("click");
        expect(wrapper.emitted("close")).toHaveLength(1);
    });
});
