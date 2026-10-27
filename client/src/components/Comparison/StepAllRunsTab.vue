<script setup lang="ts">
import { computed } from "vue";

import type { WorkflowInvocationElementView } from "@/api/invocations";
import type { WorkflowStepTyped } from "@/api/workflows";
import type { GraphStep } from "@/composables/useInvocationGraph";
import { useWorkflowStore } from "@/stores/workflowStore";

import StepRunsTab from "./StepRunsTab.vue";
import GTab from "@/components/BaseComponents/GTab.vue";

const props = defineProps<{
    invocation: WorkflowInvocationElementView;
    workflowStep: WorkflowStepTyped;
    graphStep?: GraphStep;
}>();

const workflowStore = useWorkflowStore();
// The invocation page has loaded the workflow; this reads the store without fetching.
const storedWorkflow = computed(() => workflowStore.getStoredWorkflowByInstanceId(props.invocation.workflow_id));
const storedWorkflowId = computed(() => storedWorkflow.value?.id);
// A subworkflow's run belongs to a hidden workflow per subworkflow build, so its runs would be that build's only.
const inSubworkflow = computed(() => Boolean(storedWorkflow.value?.hidden));

// The editor step carries the label; the invocation step has it once scheduled.
const stepLabel = computed(
    () => props.graphStep?.label || props.invocation.steps[props.workflowStep.id]?.workflow_step_label || undefined,
);
const title = computed(() => {
    if (inSubworkflow.value) {
        return "Steps inside a subworkflow can't be compared across runs yet";
    }
    return stepLabel.value ? "All runs" : "Label this step to compare its runs";
});
</script>

<template>
    <!-- Lazy, so step cards don't fetch runs until the tab is opened. -->
    <GTab lazy title-item-class="invocation-step-all-runs-tab" :disabled="inSubworkflow || !stepLabel" :title="title">
        <StepRunsTab
            :workflow-id="invocation.workflow_id"
            instance
            :stored-workflow-id="storedWorkflowId"
            :step-label="stepLabel"
            :current-invocation-id="invocation.id" />
    </GTab>
</template>
