import { composeStories } from "@storybook/vue3-vite";
import { emittedArg } from "@tests/vitest/helpers";
import { useStoryMount } from "@tests/vitest/stories";
import { describe, expect, it } from "vitest";
import { nextTick } from "vue";

import { useWorkflowStepStore } from "@/stores/workflowStepStore";

import * as LintStories from "./Lint.stories";

import Lint from "./Lint.vue";

const stories = composeStories(LintStories);
const mountStory = useStoryMount();

// What the review lists, and its fix-all link, are checked in the stories' play functions. The
// actions a fix emits have no visible result here, and a store edit on a live mount isn't a story.
describe("Lint", () => {
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
