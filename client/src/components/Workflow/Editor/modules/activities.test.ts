import { createTestingPinia } from "@pinia/testing";
import { setActivePinia } from "pinia";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { ref, shallowRef } from "vue";

import type { Activity } from "@/stores/activityStoreTypes";

import { applySaveIndicator, useSpecialWorkflowActivities, useWorkflowActivities } from "./activities";
import type { LintData } from "./useLinting";

function makeLintData(totalPriority = 0, resolvedPriority = 0, totalAttribute = 0, resolvedAttribute = 0): LintData {
    return {
        totalPriorityIssues: ref(totalPriority),
        resolvedPriorityIssues: ref(resolvedPriority),
        totalAttributeIssues: ref(totalAttribute),
        resolvedAttributeIssues: ref(resolvedAttribute),
    } as unknown as LintData;
}

function makeSaveActivity(): Activity {
    return {
        id: "save-workflow",
        title: "Save",
        description: "Save this workflow.",
        tooltip: "Save current changes",
        visible: true,
    };
}

function makeOtherActivity(): Activity {
    return {
        id: "workflow-editor-tools",
        title: "Tools",
        description: "Tool panel.",
        tooltip: "Search tools",
        visible: true,
    };
}

describe("useWorkflowActivities", () => {
    beforeEach(() => {
        const pinia = createTestingPinia({ createSpy: vi.fn, stubActions: false });
        setActivePinia(pinia);
    });

    it("excludes custom tools when canUseUnprivilegedTools is false", () => {
        const activities = useWorkflowActivities("workflow-editor", ref(false), ref(false), ref(0), ref(false), ref(false));
        expect(activities.value.map((a) => a.id)).not.toContain("workflow-editor-user-defined-tools");
    });

    it("includes custom tools when canUseUnprivilegedTools is true", () => {
        const activities = useWorkflowActivities("workflow-editor", ref(false), ref(false), ref(0), ref(true), ref(false));
        expect(activities.value.map((a) => a.id)).toContain("workflow-editor-user-defined-tools");
    });

    it("reflects undoStackLength reactively as the Changes activity indicator", () => {
        const undoStackLength = ref(5);
        const activities = useWorkflowActivities(
            "workflow-editor",
            ref(false),
            ref(false),
            undoStackLength,
            ref(false),
            ref(false),
        );
        const changesActivity = () => activities.value.find((a) => a.id === "workflow-undo-redo");

        expect(changesActivity()?.indicator).toBe(5);
        undoStackLength.value = 10;
        expect(changesActivity()?.indicator).toBe(10);
    });

    it("reflects hasChanges reactively as the Save activity tooltip", () => {
        const hasChanges = ref(false);
        const activities = useWorkflowActivities("workflow-editor", ref(false), hasChanges, ref(0), ref(false), ref(false));
        const saveTooltip = () => activities.value.find((a) => a.id === "save-workflow")?.tooltip;

        expect(saveTooltip()).toBe("No changes to save");
        hasChanges.value = true;
        expect(saveTooltip()).toBe("Save current changes");
    });
});

describe("applySaveIndicator", () => {
    it("shows count indicator when persistence enabled and actions pending", () => {
        const activities = [makeOtherActivity(), makeSaveActivity()];
        const result = applySaveIndicator(activities, true, 3, false);

        const save = result.find((a) => a.id === "save-workflow")!;
        expect(save.indicator).toBe(3);
        expect(save.indicatorVariant).toBe("primary");
    });

    it("shows no indicator when pending count is 0", () => {
        const activities = [makeSaveActivity()];
        const result = applySaveIndicator(activities, true, 0, false);

        const save = result.find((a) => a.id === "save-workflow")!;
        expect(save.indicator).toBeUndefined();
    });

    it("uses danger variant when saveFailed is true", () => {
        const activities = [makeSaveActivity()];
        const result = applySaveIndicator(activities, true, 2, true);

        const save = result.find((a) => a.id === "save-workflow")!;
        expect(save.indicator).toBe(2);
        expect(save.indicatorVariant).toBe("danger");
    });

    it("returns activities unchanged when persistence disabled", () => {
        const activities = [makeOtherActivity(), makeSaveActivity()];
        const result = applySaveIndicator(activities, false, 5, false);

        expect(result).toBe(activities); // same reference, no-op
    });
});

describe("useSpecialWorkflowActivities", () => {
    function setUpBestPractices(hasInvalidConnections = false, lintData = makeLintData()) {
        const { specialWorkflowActivities, exitWorkflowActivity } = useSpecialWorkflowActivities(
            shallowRef({ hasInvalidConnections, lintData }),
        );
        const bestPracticesActivity = specialWorkflowActivities.value.find((a) => a.id === "workflow-best-practices")!;
        return { bestPracticesActivity, exitWorkflowActivity };
    }

    describe("Best Practices indicator", () => {
        it("is undefined when there are no issues", () => {
            expect(setUpBestPractices().bestPracticesActivity.indicator).toBeUndefined();
        });

        it("shows remaining critical count when priority issues are unresolved", () => {
            expect(setUpBestPractices(false, makeLintData(3, 1)).bestPracticesActivity.indicator).toBe(2);
        });

        it("shows true when only minor issues remain", () => {
            expect(setUpBestPractices(false, makeLintData(0, 0, 2, 0)).bestPracticesActivity.indicator).toBe(true);
        });

        it("uses danger variant for numeric indicator and primary for icon indicator", () => {
            expect(setUpBestPractices(false, makeLintData(1, 0)).bestPracticesActivity.indicatorVariant).toBe("danger");
            expect(setUpBestPractices(false, makeLintData(0, 0, 1, 0)).bestPracticesActivity.indicatorVariant).toBe(
                "primary",
            );
        });
    });

    describe("Best Practices tooltip", () => {
        it("shows default tooltip when no issues remain", () => {
            expect(setUpBestPractices().bestPracticesActivity.tooltip).toBe("Test workflow for best practices");
        });

        it("uses singular wording for exactly 1 critical issue", () => {
            expect(setUpBestPractices(false, makeLintData(1, 0)).bestPracticesActivity.tooltip).toBe(
                "1 critical best practice issue remains",
            );
        });

        it("uses plural wording for multiple critical issues", () => {
            expect(setUpBestPractices(false, makeLintData(3, 1)).bestPracticesActivity.tooltip).toBe(
                "2 critical best practice issues remain",
            );
        });

        it("shows minor issue count when only minor issues remain", () => {
            expect(setUpBestPractices(false, makeLintData(0, 0, 2, 1)).bestPracticesActivity.tooltip).toBe(
                "1 minor best practice issue remains",
            );
        });
    });

    describe("exitWorkflowActivity tooltip", () => {
        it("shows save and exit message when connections are valid", () => {
            const { exitWorkflowActivity } = setUpBestPractices(false);
            expect(exitWorkflowActivity.value.tooltip).toBe("Save this workflow, then exit the workflow editor");
        });

        it("shows invalid connections warning when hasInvalidConnections is true", () => {
            const { exitWorkflowActivity } = setUpBestPractices(true);
            expect(exitWorkflowActivity.value.tooltip).toBe(
                "Workflow has invalid connections, review and remove invalid connections",
            );
        });
    });
});
