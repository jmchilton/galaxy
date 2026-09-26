<script setup lang="ts">
import { computed, ref, watch } from "vue";

import {
    refactor,
    type RefactorRequestAction,
    type RefactorResponse,
    type RefactorResponseActionExecution,
    type WorkflowVersion,
} from "@/api/workflows";
import { useConfirmDialog } from "@/composables/confirmDialog";
import { useToast } from "@/composables/toast";

import GAlert from "@/components/BaseComponents/GAlert.vue";
import GModal from "@/components/BaseComponents/GModal.vue";

interface Props {
    refactorActions: RefactorRequestAction[];
    versions: WorkflowVersion[];
    workflowId: string;
    version?: number;
    loading?: boolean;
}
const props = withDefaults(defineProps<Props>(), {
    version: undefined,
    loading: false,
});

const emit = defineEmits<{
    (e: "onShow"): void;
    (e: "update:loading", loading: boolean): void;
    (e: "onWorkflowError", message: string, response: any): void;
    (e: "onRefactor", data: RefactorResponse): void;
}>();

type RefactorMessage = RefactorResponseActionExecution["messages"][number];

const UPGRADE_ACTION_TYPES = ["upgrade_all_steps", "upgrade_tool", "upgrade_subworkflow"];

const show = ref(props.refactorActions.length > 0);
const confirmActionExecutions = ref<RefactorResponseActionExecution[]>([]);

const { confirm } = useConfirmDialog();
const Toast = useToast();

const isUpgrade = computed(
    () =>
        props.refactorActions.length > 0 &&
        props.refactorActions.every((action) => UPGRADE_ACTION_TYPES.includes(action.action_type)),
);

const title = computed(() => (isUpgrade.value ? "Review Workflow Upgrade" : "Potential Issues Reworking Workflow"));

const allMessages = computed(() => confirmActionExecutions.value.flatMap((execution) => execution.messages));

/** Messages without a cause come from servers predating it - treat them as forced. */
function isRequested(message: RefactorMessage) {
    return message.cause === "requested";
}

const requestedMessages = computed(() => allMessages.value.filter(isRequested));
const forcedMessages = computed(() => allMessages.value.filter((message) => !isRequested(message)));

function stepName(message: RefactorMessage) {
    if (message.step_label) {
        return message.step_label;
    }
    if (message.order_index !== null && message.order_index !== undefined) {
        return `Step ${message.order_index + 1}`;
    }
    return "Workflow";
}

function changeDescription(message: RefactorMessage) {
    if (message.message_type === "tool_version_change" && message.to_tool_version) {
        const toolId = message.to_tool_id ?? message.from_tool_id;
        return `${toolId}: ${message.from_tool_version ?? "unspecified"} → ${message.to_tool_version}`;
    }
    return message.message;
}

/** Determines if the current version is not the latest */
const isNotLatestVersion = computed(
    () =>
        (props.version === 0 || props.version) &&
        props.versions.length > 1 &&
        props.version !== props.versions[props.versions.length - 1]?.version,
);

watch(
    () => props.refactorActions,
    (newActions) => {
        if (newActions.length > 0) {
            dryRun();
        }
    },
);

watch(show, (newShow) => {
    if (newShow) {
        // emit that this is showing, so the workflow editor hides error modal.
        emit("onShow");
    }
});

async function dryRun() {
    if (isNotLatestVersion.value) {
        const contDryRun = await confirm(
            `This workflow is not the latest version. A refactor will be attempted on the specified "Version ${props.version! + 1}". Do you wish to continue?`,
            {
                title: "Confirm Refactor on Older Version",
                okText: `Yes, refactor "Version ${props.version! + 1}"`,
                cancelText: "No, cancel refactor",
            },
        );
        if (!contDryRun) {
            return;
        }
    }

    emit("update:loading", true);
    try {
        const data = await refactor(props.workflowId, props.refactorActions, "editor", true, props.version);
        await onDryRunResponse(data);
    } catch (response) {
        onError(response as string);
    } finally {
        emit("update:loading", false);
    }
}

function onError(response: string) {
    emit("onWorkflowError", "Reworking workflow failed...", response);
}

async function onDryRunResponse(data: RefactorResponse) {
    const actionExecutions = data.action_executions;
    const anyRequireConfirmation = actionExecutions.some((execution) => execution.messages.length > 0);
    if (anyRequireConfirmation) {
        confirmActionExecutions.value = actionExecutions;
        show.value = true;
    } else if (isUpgrade.value) {
        Toast.info("All tools and subworkflows in this workflow are already up to date.");
    } else {
        await executeRefactoring();
    }
}

async function executeRefactoring() {
    show.value = false;
    emit("update:loading", true);
    try {
        const data = await refactor(props.workflowId, props.refactorActions, "editor", false, props.version);
        emit("onRefactor", data);
    } catch (response) {
        onError(response as string);
    } finally {
        emit("update:loading", false);
    }
}
</script>

<template>
    <GModal
        confirm
        :show.sync="show"
        :title="title"
        fixed-height
        ok-text="Proceed"
        data-description="workflow refactor modal"
        @ok="executeRefactoring">
        <div class="workflow-refactor-modal">
            <div v-if="requestedMessages.length" data-description="refactor requested changes">
                <p>The following changes will be made to this workflow:</p>
                <table class="table table-sm">
                    <thead>
                        <tr>
                            <th>Step</th>
                            <th>Change</th>
                        </tr>
                    </thead>
                    <tbody>
                        <tr v-for="(message, index) in requestedMessages" :key="index">
                            <td>{{ stepName(message) }}</td>
                            <td>{{ changeDescription(message) }}</td>
                        </tr>
                    </tbody>
                </table>
            </div>
            <GAlert v-if="forcedMessages.length" variant="warning" data-description="refactor forced changes">
                <div v-if="requestedMessages.length">Galaxy will also need to make the following adjustments.</div>
                <div v-else>The following issues were detected when attempting to rework this workflow.</div>
                <ul class="mb-0">
                    <li v-for="(message, index) in forcedMessages" :key="index">
                        <strong>{{ stepName(message) }}:</strong> {{ message.message }}
                    </li>
                </ul>
            </GAlert>
            <div>Click "Proceed" to apply these changes, or "Cancel" to abort.</div>
        </div>
    </GModal>
</template>
