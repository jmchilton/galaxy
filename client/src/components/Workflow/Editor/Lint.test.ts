import { composeStories } from "@storybook/vue3-vite";
import { emittedArg, nth } from "@tests/vitest/helpers";
import { useStoryMount } from "@tests/vitest/stories";
import { describe, expect, it } from "vitest";
import { nextTick } from "vue";

import { useWorkflowStepStore } from "@/stores/workflowStepStore";

import * as LintStories from "./Lint.stories";

import Lint from "./Lint.vue";

const stories = composeStories(LintStories);
const mountStory = useStoryMount();

describe("Lint", () => {
    it("shows four passing checks, five warnings, and the warning links in order", () => {
        const wrapper = mountStory(stories.InputDisconnected);
        /** Passing: 4
         * - Critical: Has unique labels;
         * - Non-critical: Has annotation, creator and license
         */
        const numLintChecksPassing = 4;
        const checked = wrapper.findAll("[data-description='lint okay section']");
        expect(checked.length).toBe(numLintChecksPassing);

        /** Failing: 5
         * - Critical: untypedParameters, disconnectedInputs, missingMetadata, unlabeledOutputs
         * - Non-critical: No readme
         */
        const numLintChecksFailing = 5;
        const unchecked = wrapper.findAll("[data-description='lint warning section']");
        expect(unchecked.length).toBe(numLintChecksFailing);

        const links = wrapper.findAll("[data-description='autofix item link']");
        // Only the autofix-able issues have links
        expect(links.length).toBeGreaterThanOrEqual(4);

        // Check the order of warnings as they appear in the rendered output
        expect(nth(links, 0).text().toLowerCase()).toContain("untyped_parameter");
        expect(nth(links, 1).text().toLowerCase()).toContain("step label: input_label");
        expect(nth(links, 2).text().toLowerCase()).toContain("data input: missing an annotation");
        expect(nth(links, 3).text().toLowerCase()).toContain("step label: output");

        // Only 1 non-critical, attribute-related issue
        const attributeLink = wrapper.findAll("[data-description='attribute link']");
        expect(attributeLink.length).toBe(1);
        expect(nth(attributeLink, 0).text().toLowerCase()).toContain("provide readme for your workflow");
    });

    it("emits parameter extraction, input extraction, and unlabeled-output removal actions", async () => {
        const wrapper = mountStory(stories.InputDisconnected);
        const autoFixButton = wrapper.find("[data-description='auto fix lint issues']");
        expect(autoFixButton.exists()).toBe(true);
        await autoFixButton.trigger("click");
        const lint = wrapper.getComponent(Lint);
        expect(lint.emitted("onRefactor")).toHaveLength(1);
        expect(emittedArg(lint, "onRefactor")).toMatchObject([
            { action_type: "extract_untyped_parameter", name: "untyped_parameter" },
            { action_type: "extract_input" },
            { action_type: "remove_unlabeled_workflow_outputs" },
        ]);
    });

    it("leaves input extraction out of the autofix actions while the data input is connected", async () => {
        const wrapper = mountStory(stories.InputConnected);
        await wrapper.get("[data-description='auto fix lint issues']").trigger("click");
        const lint = wrapper.getComponent(Lint);
        expect(lint.emitted("onRefactor")).toHaveLength(1);
        expect(emittedArg(lint, "onRefactor")).toMatchObject([
            { action_type: "extract_untyped_parameter", name: "untyped_parameter" },
            { action_type: "remove_unlabeled_workflow_outputs" },
        ]);
    });

    it("adds input extraction to the autofix actions once the connected data input is removed", async () => {
        const wrapper = mountStory(stories.InputConnected);
        expect(wrapper.get("[data-description='linting connected']").attributes("data-lint-status")).toBe("ok");
        useWorkflowStepStore(stories.InputConnected.args.workflowId!).removeStep(0);
        await nextTick();
        const autoFixButton = wrapper.find("[data-description='auto fix lint issues']");
        expect(autoFixButton.exists()).toBe(true);
        await autoFixButton.trigger("click");
        const lint = wrapper.getComponent(Lint);
        expect(lint.emitted("onRefactor")).toHaveLength(1);
        expect(emittedArg(lint, "onRefactor")).toMatchObject([
            { action_type: "extract_untyped_parameter", name: "untyped_parameter" },
            { action_type: "extract_input" },
            { action_type: "remove_unlabeled_workflow_outputs" },
        ]);
    });
});
