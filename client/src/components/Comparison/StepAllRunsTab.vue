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
const storedWorkflowId = computed(() => workflowStore.getStoredWorkflowIdByInstanceId(props.invocation.workflow_id));

// The editor step carries the label; the invocation step has it once scheduled.
const stepLabel = computed(
    () => props.graphStep?.label || props.invocation.steps[props.workflowStep.id]?.workflow_step_label || undefined,
);
</script>

<template>
    <!-- Lazy, so step cards don't fetch runs until the tab is opened. -->
    <GTab
        lazy
        title-item-class="invocation-step-all-runs-tab"
        :disabled="!stepLabel"
        :title="stepLabel ? 'All runs' : 'Label this step to compare its runs'">
        <StepRunsTab
            :workflow-id="invocation.workflow_id"
            instance
            :stored-workflow-id="storedWorkflowId"
            :step-label="stepLabel"
            :current-invocation-id="invocation.id" />
    </GTab>
</template>
