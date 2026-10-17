<script setup lang="ts">
import { BLink } from "bootstrap-vue";
import { computed, onMounted, ref, watch } from "vue";
import { RouterLink, useRouter } from "vue-router";

import { canMutateHistory } from "@/api";
import type { WorkflowInvocationRequest, WorkflowInvocationRequestInputs } from "@/api/invocations";
import { getWorkflowInfo } from "@/api/workflows";
import { copyWorkflow } from "@/components/Workflow/workflows.services";
import { useWorkflowInstance } from "@/composables/useWorkflowInstance";
import { useHistoryItemsStore } from "@/stores/historyItemsStore";
import { useHistoryStore } from "@/stores/historyStore";
import { useUserStore } from "@/stores/userStore";
import { errorMessageAsString } from "@/utils/simple-error";

import { rerunHasStepParameters, WorkflowRunModel } from "./model";
import { getRunData, WorkflowMissingToolsError } from "./services";
import { simpleFormDisabledReason } from "./simpleFormDisabledReason";

import GAlert from "@/components/BaseComponents/GAlert.vue";
import LoadingSpan from "@/components/LoadingSpan.vue";
import WorkflowMissingToolsRequest from "@/components/Workflow/Run/WorkflowMissingToolsRequest.vue";
import WorkflowRunForm from "@/components/Workflow/Run/WorkflowRunForm.vue";
import WorkflowRunFormSimple from "@/components/Workflow/Run/WorkflowRunFormSimple.vue";
import WorkflowRunSuccess from "@/components/Workflow/Run/WorkflowRunSuccess.vue";

const historyStore = useHistoryStore();
const historyItemsStore = useHistoryItemsStore();
const userStore = useUserStore();
const router = useRouter();

interface Props {
    workflowId: string;
    version?: string;
    preferSimpleForm?: boolean;
    simpleFormTargetHistory?: string;
    simpleFormUseJobCache?: boolean;
    requestState?: WorkflowInvocationRequestInputs;
    /** Exported request of the invocation being rerun, prefills the expanded form */
    rerunRequest?: WorkflowInvocationRequest;
    /** Invocation being rerun, seeds tool and subworkflow steps with the values it ran with */
    rerunInvocationId?: string;
    instance?: boolean;
    isRerun?: boolean;
    landingUuid?: string;
}

const props = withDefaults(defineProps<Props>(), {
    version: undefined,
    preferSimpleForm: false,
    simpleFormTargetHistory: "current",
    simpleFormUseJobCache: false,
    requestState: undefined,
    rerunRequest: undefined,
    rerunInvocationId: undefined,
    instance: false,
    isRerun: false,
    landingUuid: undefined,
});

const loading = ref(true);
const hasUpgradeMessages = ref(false);
const hasStepVersionChanges = ref(false);
const invocations = ref([]);
const submissionError = ref("");
const workflowError = ref("");
const missingToolIds = ref<string[]>([]);
const workflowName = ref("");
const workflowModel: any = ref(null);
const disableSimpleFormReason = computed(() =>
    props.preferSimpleForm && workflowModel.value ? simpleFormDisabledReason(workflowModel.value) : undefined,
);
const disableSimpleForm = computed(() => disableSimpleFormReason.value !== undefined);
// The simple form never submits tool step parameters, so a rerun would drop them.
const simpleForm = computed(
    () =>
        props.preferSimpleForm &&
        !disableSimpleForm.value &&
        !(props.isRerun && rerunHasStepParameters(props.rerunRequest)),
);
const owner = ref<string>();
// The StoredWorkflow this run page is for. In instance mode `props.workflowId`
// is a Workflow (instance) id, which must not be sent with a tool installation
// request: the server validates and links `workflow_id` as a StoredWorkflow id.
const storedWorkflowId = ref<string | undefined>(props.instance ? undefined : props.workflowId);

const currentHistoryId = computed(() => historyStore.currentHistoryId);
const editorLink = computed(() => {
    const queryArgs = {
        [props.instance ? "workflow_id" : "id"]: props.workflowId,
        ...(props.version && { version: props.version }),
    };
    return router.resolve({ path: "/workflows/edit", query: queryArgs }).href;
});
const historyStatusKey = computed(() => `${currentHistoryId.value}_${lastUpdateTime.value}`);
const isOwner = computed(() => userStore.matchesCurrentUsername(owner.value));
const lastUpdateTime = computed(() => historyItemsStore.lastUpdateTime);
const canRunOnHistory = computed(() => {
    if (!currentHistoryId.value) {
        return false;
    }
    const history = historyStore.getHistoryById(currentHistoryId.value);
    return (history && canMutateHistory(history)) ?? false;
});

if (props.instance) {
    const { workflow } = useWorkflowInstance(props.workflowId);
    watch(workflow, () => {
        if (workflow.value) {
            workflowName.value = workflow.value?.name;
            owner.value = workflow.value?.owner;
            storedWorkflowId.value = workflow.value?.id;
        }
    });
}

function handleInvocations(incomingInvocations: any) {
    if (incomingInvocations.length === 1) {
        router.push(`/workflows/invocations/${incomingInvocations[0].id}?success=true`);
    } else {
        invocations.value = incomingInvocations;
        // make sure any new histories are added to historyStore
        invocations.value.forEach((invocation: any) => {
            historyStore.getHistoryById(invocation.history_id);
        });
    }
}

function handleSubmissionError(error: string) {
    submissionError.value = errorMessageAsString(error);
}

async function loadRun() {
    try {
        const runData = await getRunData(
            props.workflowId,
            props.version || undefined,
            props.instance,
            props.rerunInvocationId,
        );
        const incomingModel = new WorkflowRunModel(runData);
        hasUpgradeMessages.value = incomingModel.hasUpgradeMessages;
        hasStepVersionChanges.value = incomingModel.hasStepVersionChanges;
        workflowName.value = incomingModel.name;
        workflowModel.value = incomingModel;
        owner.value = incomingModel.runData.owner;
        // loadRun re-runs on history changes: a successful reload clears any
        // error state left by an earlier attempt.
        workflowError.value = "";
        missingToolIds.value = [];
        loading.value = false;
    } catch (e) {
        if (e instanceof WorkflowMissingToolsError) {
            workflowError.value = e.message;
            missingToolIds.value = e.missingToolIds;
            if (!workflowName.value) {
                try {
                    const storedWorkflow = await getWorkflowInfo(props.workflowId, undefined, props.instance);
                    owner.value = storedWorkflow.owner;
                    workflowName.value = storedWorkflow.name;
                    if (props.instance) {
                        storedWorkflowId.value = storedWorkflow.id;
                    }
                } catch {
                    // best-effort: name not critical for the request button
                }
            }
        } else {
            // Only a missing-tools failure may offer the install request.
            missingToolIds.value = [];
            const errMessage = errorMessageAsString(e);
            if (errMessage === "Workflow step has upgrade messages") {
                hasUpgradeMessages.value = true;
                if (!props.instance) {
                    try {
                        const storedWorkflow = await getWorkflowInfo(props.workflowId);
                        owner.value = storedWorkflow.owner;
                        workflowName.value = storedWorkflow.name;
                    } catch {
                        // just show original error
                        workflowError.value = errMessage;
                    }
                }
            } else {
                workflowError.value = errMessage;
            }
        }
        loading.value = false;
    }
}

async function onImport() {
    const response = await copyWorkflow(props.workflowId, owner.value, props.version);
    router.push(`/workflows/edit?id=${response.id}`);
}

const advancedForm = ref(false);
const fromVariant = computed<"simple" | "advanced">(() => {
    if (advancedForm.value) {
        return "advanced";
    } else if (simpleForm.value) {
        return "simple";
    } else {
        return "advanced";
    }
});

function showAdvanced() {
    advancedForm.value = true;
}

onMounted(() => {
    loadRun();
});

watch(
    () => historyStatusKey.value,
    () => {
        if (invocations.value.length === 0) {
            loadRun();
        }
    },
);

defineExpose({
    loading,
    simpleForm,
    submissionError,
    handleSubmissionError,
    workflowError,
    workflowModel,
});
</script>

<template>
    <span>
        <GAlert v-if="workflowError" variant="danger" show>
            <h2 class="h-text">Workflow cannot be executed. Please resolve the following issue:</h2>
            {{ workflowError }}
            <WorkflowMissingToolsRequest :missing-tool-ids="missingToolIds" :workflow-id="storedWorkflowId" />
        </GAlert>
        <span v-else>
            <GAlert v-if="loading" variant="info" show>
                <LoadingSpan message="Loading workflow run data" />
            </GAlert>
            <WorkflowRunSuccess
                v-else-if="invocations.length > 0"
                :invocations="invocations"
                :workflow-name="workflowName" />
            <div v-else class="h-100">
                <GAlert
                    v-if="hasUpgradeMessages || hasStepVersionChanges"
                    class="mb-4"
                    variant="warning"
                    show
                    data-description="workflow run warning">
                    <span>
                        The <b>`{{ workflowName }}`</b> workflow may contain tools which have changed since it was last
                        saved or some other problems have been detected. Please
                    </span>
                    <RouterLink v-if="isOwner" :to="editorLink">click here to edit and review the issues</RouterLink>
                    <BLink v-else @click="onImport">click here to import the workflow and review the issues</BLink>
                    <span>before running this workflow.</span>
                </GAlert>
                <div v-else class="h-100">
                    <GAlert
                        v-if="submissionError"
                        class="mb-4"
                        variant="danger"
                        data-description="workflow run error"
                        show>
                        Workflow submission failed: {{ submissionError }}
                    </GAlert>
                    <WorkflowRunFormSimple
                        v-if="fromVariant === 'simple'"
                        :model="workflowModel"
                        :target-history="simpleFormTargetHistory"
                        :use-job-cache="simpleFormUseJobCache"
                        :can-mutate-current-history="canRunOnHistory"
                        :request-state="requestState"
                        :is-rerun="props.isRerun"
                        :landing-uuid="props.landingUuid"
                        @submissionSuccess="handleInvocations"
                        @submissionError="handleSubmissionError"
                        @showAdvanced="showAdvanced" />
                    <WorkflowRunForm
                        v-else
                        :model="workflowModel"
                        :can-mutate-current-history="canRunOnHistory"
                        :disable-simple-form="disableSimpleForm"
                        :disable-simple-form-reason="disableSimpleFormReason"
                        :rerun-request="rerunRequest"
                        @submissionSuccess="handleInvocations"
                        @submissionError="handleSubmissionError"
                        @showSimple="advancedForm = false" />
                </div>
            </div>
        </span>
    </span>
</template>
