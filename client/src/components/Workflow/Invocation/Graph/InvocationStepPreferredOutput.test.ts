import { getLocalVue } from "@tests/vitest/helpers";
import { shallowMount } from "@vue/test-utils";
import { describe, expect, it } from "vitest";

import type { GraphStep } from "@/composables/useInvocationGraph";

import InvocationOutputSnapshot from "./InvocationOutputSnapshot.vue";
import InvocationStepPreferredOutput from "./InvocationStepPreferredOutput.vue";

function mountPreferredOutput(step: Partial<GraphStep>) {
    return shallowMount(InvocationStepPreferredOutput as object, {
        propsData: { item: { src: "hda", id: "d1" }, step: { id: 4, state: "ok", ...step } },
        localVue: getLocalVue(),
    });
}

function labelOf(step: Partial<GraphStep>) {
    return mountPreferredOutput(step).find("[data-description='invocation step preferred output label']").text();
}

describe("InvocationStepPreferredOutput", () => {
    it("snapshots the item under the step's state", () => {
        const snapshot = mountPreferredOutput({ preferred_output: "out_file1" }).findComponent(
            InvocationOutputSnapshot,
        );
        expect(snapshot.props()).toMatchObject({ item: { src: "hda", id: "d1" }, step: { id: 4, state: "ok" } });
    });

    it("is labelled with the workflow output's label, as its card would have been", () => {
        const label = labelOf({
            preferred_output: "out_file1",
            workflow_outputs: [
                { output_name: "out_file2", label: "other" },
                { output_name: "out_file1", label: "top_rows" },
            ],
        });
        expect(label).toBe("top_rows");
    });

    it("is labelled with the output's name when it isn't a labelled workflow output", () => {
        expect(labelOf({ preferred_output: "out_file1" })).toBe("out_file1");
        expect(labelOf({ preferred_output: "out_file1", workflow_outputs: [{ output_name: "out_file1" }] })).toBe(
            "out_file1",
        );
    });
});
