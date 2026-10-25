<script setup lang="ts">
import { faReadme } from "@fortawesome/free-brands-svg-icons";
import { faArrowRight, faCog, faPlus, faSitemap, faTimes } from "@fortawesome/free-solid-svg-icons";
import { FontAwesomeIcon } from "@fortawesome/vue-fontawesome";
import { BFormInput } from "bootstrap-vue";
import { storeToRefs } from "pinia";
import { computed, onBeforeMount, ref, watch } from "vue";

import type { WriteStoreToPayload } from "@/api/exports";
import type { WorkflowInvocationRequest, WorkflowInvocationRequestInputs } from "@/api/invocations";
import type { ToolIdentifier } from "@/api/tools";
import type { DataOption } from "@/components/Form/Elements/FormData/types";
import { DEFAULT_OPTIONS_PAGE_SIZE } from "@/components/Form/Elements/FormData/types";
import type { FormParameterTypes } from "@/components/Form/parameterTypes";
import { isWorkflowInput } from "@/components/Workflow/constants";
import { useConfig } from "@/composables/config";
import { useFileSources } from "@/composables/fileSources";
import { usePersistentToggle } from "@/composables/persistentToggle";
import { usePanels } from "@/composables/usePanels";
import { useUserMultiToolCredentials } from "@/composables/userMultiToolCredentials";
import { useWorkflowInstance } from "@/composables/useWorkflowInstance";
import { provideScopedWorkflowStores } from "@/composables/workflowStores";
import { useHistoryStore } from "@/stores/historyStore";
import { useToolsServiceCredentialsDefinitionsStore } from "@/stores/toolsServiceCredentialsDefinitionsStore";
import { useUserStore } from "@/stores/userStore";
import type { Step } from "@/stores/workflowStepStore";
import localize from "@/utils/localization";
import { errorMessageAsString } from "@/utils/simple-error";

import { rerunInputValue, withRerunValues } from "./model";
import { invokeWorkflow, searchHistoryContents } from "./services";
import {
    buildStepParameterTree,
    exposedParametersPayload,
    rerunStepParameterValue,
    resolveExposureKeys,
    type StepParameterNode,
} from "./stepParameterTree";

import WorkflowAnnotation from "../WorkflowAnnotation.vue";
import WorkflowNavigationTitle from "../WorkflowNavigationTitle.vue";
import ExportOnCompleteWizard from "./ExportOnCompleteWizard.vue";
import StepParameterPicker from "./StepParameterPicker.vue";
import WorkflowHelpDisplay from "./WorkflowHelpDisplay.vue";
import WorkflowRunGraph from "./WorkflowRunGraph.vue";
import WorkflowStorageConfiguration from "./WorkflowStorageConfiguration.vue";
import GAlert from "@/components/BaseComponents/GAlert.vue";
import GButton from "@/components/BaseComponents/GButton.vue";
import GButtonGroup from "@/components/BaseComponents/GButtonGroup.vue";
import GCheckbox from "@/components/BaseComponents/GCheckbox.vue";
import GModal from "@/components/BaseComponents/GModal.vue";
import GOverlay from "@/components/BaseComponents/GOverlay.vue";
import Heading from "@/components/Common/Heading.vue";
import FormDisplay from "@/components/Form/FormDisplay.vue";
import HelpText from "@/components/Help/HelpText.vue";
import LoadingSpan from "@/components/LoadingSpan.vue";
import WorkflowCredentials from "@/components/Workflow/Run/WorkflowCredentials.vue";

interface Props {
    model: Record<string, any>;
    targetHistory?: string;
    useJobCache?: boolean;
    canMutateCurrentHistory: boolean;
    requestState?: WorkflowInvocationRequestInputs;
    /** Exported request of the invocation being rerun, prefills workflow parameters and storage */
    rerunRequest?: WorkflowInvocationRequest;
    isRerun?: boolean;
    landingUuid?: string;
    /** Exposure keys (``<step_index>|<prefixed name>``) of step parameters to show on load */
    exposedStepParams?: string[];
    /** Preset values for exposed step parameters, by exposure key */
    exposedStepParamValues?: Record<string, string>;
}

type PaginatedDataOption = Pick<DataOption, "id" | "src" | "name" | "hid" | "keep" | "tags">;

const props = withDefaults(defineProps<Props>(), {
    targetHistory: "current",
    useJobCache: false,
    requestState: undefined,
    rerunRequest: undefined,
    isRerun: false,
    landingUuid: undefined,
    exposedStepParams: () => [],
    exposedStepParamValues: () => ({}),
});

const emit = defineEmits<{
    (e: "showAdvanced"): void;
    (e: "submissionSuccess", invocations: any): void;
    (e: "submissionError", error: string): void;
}>();

const { currentUser } = storeToRefs(useUserStore());
const { currentHistoryId, changingCurrentHistory } = storeToRefs(useHistoryStore());

const { stateStore } = provideScopedWorkflowStores(props.model.workflowId);
const { activeNodeId } = storeToRefs(stateStore);

const { config, isConfigLoaded } = useConfig();
const { showPanels } = usePanels();

const formData = ref<Record<string, any>>({});
const inputTypes = ref<Record<string, string>>({});
const stepValidation = ref<[string, string] | null>(null);
const sendToNewHistory = ref(props.targetHistory === "new" || props.targetHistory === "prefer_new");
const newHistoryName = ref(props.model.name);
const useCachedJobs = ref(props.useJobCache);
// The invoke API accepts either a single preferred object store or the split pair, never both.
const rerunSplitObjectStore = Boolean(
    props.rerunRequest?.preferred_outputs_object_store_id || props.rerunRequest?.preferred_intermediate_object_store_id,
);
const splitObjectStore = ref(rerunSplitObjectStore);
const preferredObjectStoreId = ref<string | null>(
    (rerunSplitObjectStore
        ? props.rerunRequest?.preferred_outputs_object_store_id
        : props.rerunRequest?.preferred_object_store_id) ?? null,
);
const preferredIntermediateObjectStoreId = ref<string | null>(
    props.rerunRequest?.preferred_intermediate_object_store_id ?? null,
);
const waitingForRequest = ref(false);
const showRightPanel = ref<"help" | "graph" | null>(null);
const checkInputMatching = ref(props.requestState !== undefined);
const sendNotificationOnComplete = ref(false);
const showExportWizard = ref(false);
const exportCheckboxKey = ref(0);
const exportOnCompleteConfig = ref<WriteStoreToPayload | null>(null);

const { hasWritable: hasWritableFileSources } = useFileSources({ exclude: ["rdm"] });

const showGraph = computed(() => showRightPanel.value === "graph");
const showHelp = computed(() => showRightPanel.value === "help");

const { toggled: showRuntimeSettingsPanel, toggle: toggleRuntimeSettings } =
    usePersistentToggle("workflow-run-settings-panel");

// Workflow REAME/help panel setup
const { workflow, loading: workflowLoading } = useWorkflowInstance(props.model.runData.workflow_id);
watch(
    () => workflow.value,
    (workflow) => {
        if (workflow) {
            // once the workflow loads, and if we are not showing panels, show the help if it exists by default
            showRightPanel.value = !showPanels.value && workflow.readme ? "help" : null;
        }
    },
    { immediate: true },
);

watch(
    () => showGraph.value,
    (show) => {
        if (!show) {
            activeNodeId.value = null;
        }
    },
);
const computedActiveNodeId = computed<number | undefined>(() => {
    if (showGraph.value) {
        if (activeNodeId.value !== null && activeNodeId.value !== undefined) {
            return activeNodeId.value;
        }
    }
    return undefined;
});

// ``stepInputByIndex`` maps ``step.step_index`` (as string) to the live
// step-input object inside ``formInputs.value`` so the paginated-fetch
// handlers can locate and mutate it in O(1) without walking the array.
const formInputs = ref<any[]>([]);
const stepInputByIndex = new Map<string, any>();

function buildFormInputs() {
    const inputs: any[] = [];
    stepInputByIndex.clear();
    // Add workflow parameters - do we want to keep the color if we're not showing steps?
    const wpInputs = Object.values(props.model.wpInputs).map((input: any) => ({ ...input, color: undefined }));
    withRerunValues(wpInputs, props.rerunRequest?.replacement_params).forEach((input) => {
        inputs.push(input);
        inputTypes.value[input.name] = "replacement_parameter";
    });
    // Add actual input modules.
    props.model.steps.forEach((step: any, i: number) => {
        if (isWorkflowInput(step.step_type)) {
            const stepName = new String(step.step_index) as any;
            const stepLabel = step.step_label || new String(step.step_index + 1);

            const stepType = step.step_type;
            const help = step.annotation;
            const longFormInput = step.inputs[0];
            const stepAsInput = Object.assign({}, longFormInput, {
                name: stepName,
                help: help,
                label: stepLabel,
            });

            if (props.requestState) {
                if (props.isRerun) {
                    const value = rerunInputValue(props.requestState, step, i);
                    if (value !== undefined) {
                        stepAsInput.value = value;
                    }
                } else if (String(stepLabel) in props.requestState) {
                    stepAsInput.value = props.requestState[String(stepLabel)];
                }
            }

            // disable collection mapping...
            stepAsInput.flavor = "module";
            inputs.push(stepAsInput);
            stepInputByIndex.set(String(step.step_index), stepAsInput);
            inputTypes.value[stepName] = stepType;
        }
    });
    formInputs.value = inputs;
}

buildFormInputs();
watch(() => [props.model, props.requestState, props.rerunRequest], buildFormInputs);

// Step parameters the user chose to set for this run, sent as ``parameters`` overrides.
const stepParameterTree = computed(() => buildStepParameterTree(props.model as { steps: any[] }));
const showStepParameterPicker = ref(false);
const exposedLeaves = ref<StepParameterNode[]>([]);
const droppedStepParams = ref<{ key: string; reason: string }[]>([]);
const stepParamInputs = new Map<string, any[]>();
const stepParamKeyByName = new Map<string, string>();
const stepParamValues = ref<Record<string, unknown>>({});
const exposedKeys = computed(() => exposedLeaves.value.map((leaf) => leaf.key as string));

function stepParamInput(leaf: StepParameterNode, value: unknown): any[] {
    const name = `step_param_${stepParamKeyByName.size}`;
    stepParamKeyByName.set(name, leaf.key as string);
    const input = { ...JSON.parse(JSON.stringify(leaf.input)), name, label: leaf.label, flavor: undefined };
    delete input.collapsible_value;
    delete input.collapsible_preview;
    if (value !== undefined) {
        input.value = value;
    }
    return [input];
}

function addStepParams(keys: string[], presets: Record<string, unknown> = {}) {
    const resolved = resolveExposureKeys(stepParameterTree.value, [...exposedKeys.value, ...keys]);
    droppedStepParams.value = [...droppedStepParams.value, ...resolved.dropped];
    for (const leaf of resolved.leaves) {
        const key = leaf.key as string;
        if (!stepParamInputs.has(key)) {
            stepParamInputs.set(key, stepParamInput(leaf, presets[key]));
        }
    }
    exposedLeaves.value = resolved.leaves;
}

function removeStepParam(key: string) {
    exposedLeaves.value = exposedLeaves.value.filter((leaf) => leaf.key !== key);
    stepParamInputs.delete(key);
    const { [key]: _removed, ...rest } = stepParamValues.value;
    stepParamValues.value = rest;
}

function onStepParamChange(data: Record<string, unknown>) {
    const values = { ...stepParamValues.value };
    for (const [name, value] of Object.entries(data)) {
        const key = stepParamKeyByName.get(name);
        if (key) {
            values[key] = value;
        }
    }
    stepParamValues.value = values;
}

function displayValue(value: unknown): string {
    return value === null || value === undefined || value === "" ? "(empty)" : String(value);
}

{
    const rerunKeys = ((props.rerunRequest as any)?.exposed_step_parameters as string[] | undefined) || [];
    const presets: Record<string, unknown> = {};
    for (const key of rerunKeys) {
        presets[key] = rerunStepParameterValue(props.rerunRequest?.parameters as any, key);
    }
    Object.assign(presets, props.exposedStepParamValues);
    const initialKeys = [...new Set([...rerunKeys, ...props.exposedStepParams])];
    if (initialKeys.length) {
        addStepParams(initialKeys, presets);
    }
}

/**
 * Returns the list of steps that do not match the workflow rerun `props.requestState`.
 *
 * TODO: Until form elements are typed better, this is a little shady.
 * We do not compare values for the types in the last `else if` statement.
 * And for the `select` type, we assume that the values are arrays of strings or numbers.
 * @returns {string[]} The list of steps indices that do not match the request state.
 */
const stepsNotMatchingRequest = computed<string[]>(() => {
    if (!props.isRerun || !checkInputMatching.value || !props.requestState) {
        return [];
    }

    const inputs = formInputs.value;
    const data = formData.value;
    const notMatching: string[] = [];

    for (const input of inputs) {
        if (input.name in data) {
            const type = input.type as FormParameterTypes;

            if ((type === "data" || type === "data_collection") && input.value?.values && data[input.name]?.values) {
                const expectedValues = input.value.values as DataOption[];
                const actualValues = data[input.name].values as DataOption[];

                const matches =
                    Array.isArray(expectedValues) &&
                    Array.isArray(actualValues) &&
                    expectedValues?.length === actualValues?.length &&
                    expectedValues.every((value, index) => {
                        return value.src === actualValues[index]?.src && value.id === actualValues[index].id;
                    });

                if (!matches) {
                    notMatching.push(input.name as string);
                }
            } else if (type === "select") {
                const expectedValues = (Array.isArray(input.value) ? input.value : [input.value]) as (
                    | string
                    | number
                )[];
                const actualValues = (Array.isArray(data[input.name]) ? data[input.name] : [data[input.name]]) as (
                    | string
                    | number
                )[];

                const matches =
                    expectedValues.length === actualValues.length &&
                    expectedValues.every((value, index) => {
                        return value === actualValues[index];
                    });

                if (!matches) {
                    notMatching.push(input.name as string);
                }
            } else if (
                !["drill_down", "group_tag", "ftpfile", "upload", "rules", "tags"].includes(type) &&
                input.value !== data[input.name]
            ) {
                notMatching.push(input.name as string);
            }
        }
    }
    return notMatching;
});

const isValidRerun = computed(
    () => Boolean(props.isRerun) && checkInputMatching.value && stepsNotMatchingRequest.value.length === 0,
);

const hasValidationErrors = computed(() => stepValidation.value !== null);

const canRunOnHistory = computed(() => props.canMutateCurrentHistory || sendToNewHistory.value);

function onValidation(validation: [string, string] | null) {
    if (validation && validation.length == 2) {
        stepValidation.value = [validation[0], validation[1]];
    } else {
        stepValidation.value = null;
    }
}

function onChange(data: any) {
    formData.value = data;
}

function shapeContentsRow(row: any): PaginatedDataOption {
    const src = row.history_content_type === "dataset_collection" ? "hdca" : "hda";
    return {
        id: row.id,
        src,
        name: row.name,
        hid: row.hid,
        keep: false,
        tags: row.tags || [],
    };
}

async function fetchStepOptions(
    name: string,
    src: string,
    payload: { offset?: number; limit?: number; search?: string } = {},
) {
    // ``stepAsInput`` is a local copy built in ``buildFormInputs``, so this
    // does not mutate the model prop.
    const input = stepInputByIndex.get(String(name));
    if (!input) {
        return;
    }
    const type = src === "hdca" ? "dataset_collection" : "dataset";
    const extensions = (input.acceptable_extensions || []) as string[];
    const limit = payload.limit || DEFAULT_OPTIONS_PAGE_SIZE;
    const offset = payload.offset || 0;
    try {
        const rows = await searchHistoryContents(props.model.historyId, {
            extensions,
            type,
            tag: input.tag,
            // ``data_collection`` parameters offer hidden collections too.
            visibleOnly: input.type !== "data_collection",
            search: payload.search,
            offset,
            limit,
        });
        const shaped: PaginatedDataOption[] = (rows || []).map(shapeContentsRow);
        const base = (input.options?.[src] as PaginatedDataOption[]) || [];
        const seen = new Set<string>(base.map((item) => `${item.id}_${item.src}`));
        const merged = base.concat(
            shaped.filter((item) => {
                const key = `${item.id}_${item.src}`;
                if (seen.has(key)) {
                    return false;
                }
                seen.add(key);
                return true;
            }),
        );
        input.options = { ...(input.options || {}), [src]: merged };
        input.options_meta = {
            ...(input.options_meta || {}),
            [src]: { offset, limit, has_more: shaped.length === limit },
        };
        // FormDisplay renders from an internal clone and only syncs
        // server-owned attributes when the inputs prop changes by identity.
        // A shallow array copy triggers that sync while preserving the clone's
        // client-owned value and focused multiselect input.
        formInputs.value = [...formInputs.value];
    } catch (e) {
        // intentionally silent — paging failures don't block the rest of the form
        console.warn("history-contents pagination failed", e);
    }
}

function onLoadMore({
    name,
    src,
    offset,
    limit,
    search,
}: {
    name: string;
    src: string;
    offset: number;
    limit: number;
    search?: string;
}) {
    fetchStepOptions(name, src, { offset, limit, search });
}

function onSearchChange({ name, src, query, limit }: { name: string; src: string; query: string; limit?: number }) {
    fetchStepOptions(name, src, { offset: 0, limit: limit || DEFAULT_OPTIONS_PAGE_SIZE, search: query });
}

function onStorageUpdate(objectStoreId: string | null, intermediate: boolean) {
    if (intermediate) {
        preferredIntermediateObjectStoreId.value = objectStoreId;
    } else {
        preferredObjectStoreId.value = objectStoreId;
    }
}

function updateActiveNodeId(nodeId: number | null) {
    activeNodeId.value = nodeId;
}

function onExportConfigured(config: typeof exportOnCompleteConfig.value) {
    exportOnCompleteConfig.value = config;
    showExportWizard.value = false;
}

function clearExportConfig() {
    exportOnCompleteConfig.value = null;
}

function onExportWizardCancel() {
    showExportWizard.value = false;
    // Force checkbox to re-render and reset to unchecked state if no config was set
    if (exportOnCompleteConfig.value === null) {
        exportCheckboxKey.value++;
    }
}

const exportEnabled = computed({
    get: () => exportOnCompleteConfig.value !== null,
    set: (value: boolean) => {
        if (value) {
            // User wants to enable - open wizard, don't actually enable yet
            showExportWizard.value = true;
        } else {
            // User wants to disable - clear the config
            clearExportConfig();
        }
    },
});

async function onExecute() {
    waitingForRequest.value = true;

    const replacementParams: Record<string, any> = {};
    const inputs: Record<string, any> = {};
    for (const inputName in formData.value) {
        const value = formData.value[inputName];
        const inputType = inputTypes.value[inputName];
        if (inputType == "replacement_parameter") {
            replacementParams[inputName] = value;
        } else if (inputType && isWorkflowInput(inputType as Step["type"])) {
            // Unset optional `data` / `data_collection` inputs surface here as `null`
            // (FormData.vue's createValue returns null for `undefined`). Omit them so
            // the server-side workflow scheduler sees a missing key rather than `None`,
            // matching the working API submission shape and the rerun-branch filter above.
            const isData = inputType === "data_input" || inputType === "data_collection_input";
            if (isData && (value === null || value === undefined)) {
                continue;
            }
            inputs[inputName] = value;
        }
    }
    const onCompleteActions: any[] = [];
    if (sendNotificationOnComplete.value) {
        onCompleteActions.push({ send_notification: {} });
    }
    if (exportOnCompleteConfig.value) {
        onCompleteActions.push({ export_to_file_source: exportOnCompleteConfig.value });
    }

    const data: Record<string, any> = {
        replacement_params: replacementParams,
        inputs: inputs,
        inputs_by: "step_index",
        batch: true,
        use_cached_job: useCachedJobs.value,
        require_exact_tool_versions: false,
        version: props.model.runData.version,
        on_complete: onCompleteActions.length > 0 ? onCompleteActions : null,
    };
    if (props.landingUuid) {
        data.landing_uuid = props.landingUuid;
    }
    if (exposedLeaves.value.length) {
        const values: Record<string, unknown> = {};
        for (const leaf of exposedLeaves.value) {
            const key = leaf.key as string;
            values[key] =
                key in stepParamValues.value ? stepParamValues.value[key] : stepParamInputs.get(key)?.[0].value;
        }
        data.parameters = exposedParametersPayload(values);
        data.parameters_normalized = true;
        data.exposed_step_parameters = exposedKeys.value;
    }
    if (sendToNewHistory.value) {
        data.new_history_name = newHistoryName.value;
    } else {
        data.history_id = props.model.historyId;
    }
    if (splitObjectStore.value) {
        if (preferredObjectStoreId.value != null) {
            data.preferred_outputs_object_store_id = preferredObjectStoreId.value;
        }
        if (preferredIntermediateObjectStoreId.value != null && splitObjectStore.value) {
            data.preferred_intermediate_object_store_id = preferredIntermediateObjectStoreId.value;
        }
    } else {
        if (preferredObjectStoreId.value != null) {
            data.preferred_object_store_id = preferredObjectStoreId.value;
        }
    }

    try {
        const invocations = await invokeWorkflow(props.model.workflowId, data);
        emit("submissionSuccess", invocations);
    } catch (error) {
        emit("submissionError", errorMessageAsString(error));
    } finally {
        waitingForRequest.value = false;
    }
}

const { setToolServiceCredentialsDefinitionFor } = useToolsServiceCredentialsDefinitionsStore();

const credentialTools = computed<ToolIdentifier[]>(() => {
    const credentialSteps = props.model.steps.filter(
        (step: any) => step.step_type === "tool" && step.credentials?.length,
    );

    const toolIdentifiers: ToolIdentifier[] = [];

    credentialSteps.forEach((step: any) => {
        setToolServiceCredentialsDefinitionFor(step.id, step.version, step.credentials);
        toolIdentifiers.push({
            toolId: step.id,
            toolVersion: step.version,
        });
    });

    return toolIdentifiers;
});

const hasCredentialErrors = computed(() => {
    if (credentialTools.value.length) {
        const { hasUserProvidedAllRequiredToolsServiceCredentials } = useUserMultiToolCredentials(
            credentialTools.value,
        );
        return !hasUserProvidedAllRequiredToolsServiceCredentials.value;
    }
    return false;
});

onBeforeMount(() => {
    const credentialSteps = props.model.steps.filter(
        (step: any) => step.step_type === "tool" && step.credentials?.length,
    );
    if (credentialSteps.length) {
        const promises = credentialSteps.map((step: any) =>
            setToolServiceCredentialsDefinitionFor(step.id, step.version, step.credentials),
        );
        return Promise.all(promises);
    }
});
</script>

<template>
    <div
        v-if="currentUser && currentHistoryId"
        class="d-flex flex-column h-100 workflow-run-form-simple"
        data-galaxy-file-drop-target>
        <div v-if="!showRightPanel" class="ui-form-header-underlay sticky-top" />
        <div v-if="isConfigLoaded" :class="{ 'sticky-top': !showRightPanel }">
            <GAlert v-if="!canRunOnHistory" variant="warning" show>
                <span v-localize>
                    The workflow cannot run because the current history is immutable. Please select a different history
                    or send the results to a new one using the run settings ⚙️
                </span>
            </GAlert>
            <div class="mb-2">
                <WorkflowNavigationTitle
                    :workflow-id="model.runData.workflow_id"
                    :run-disabled="hasValidationErrors || !canRunOnHistory || hasCredentialErrors"
                    :run-waiting="waitingForRequest"
                    :valid-rerun="isValidRerun"
                    @on-execute="onExecute">
                    <template v-slot:workflow-title-actions>
                        <GButtonGroup>
                            <GButton
                                tooltip
                                size="small"
                                :title="localize(!showGraph ? 'Show workflow graph' : 'Hide workflow graph')"
                                transparent
                                color="blue"
                                :pressed="showGraph"
                                @click="showRightPanel = showGraph ? null : 'graph'">
                                <FontAwesomeIcon :icon="faSitemap" fixed-width />
                            </GButton>
                            <GButton
                                v-if="workflow?.readme || workflow?.help"
                                tooltip
                                size="small"
                                :title="localize(!showHelp ? 'Show workflow help' : 'Hide workflow help')"
                                transparent
                                color="blue"
                                :pressed="showHelp"
                                @click="showRightPanel = showHelp ? null : 'help'">
                                <FontAwesomeIcon :icon="faReadme" fixed-width />
                            </GButton>
                        </GButtonGroup>
                        <GButton
                            tooltip
                            size="small"
                            :title="localize('Workflow Run Settings')"
                            transparent
                            color="blue"
                            class="workflow-run-settings"
                            data-test-id="workflow-run-settings-button"
                            :pressed="showRuntimeSettingsPanel"
                            @click="toggleRuntimeSettings">
                            <FontAwesomeIcon :icon="faCog" fixed-width />
                        </GButton>
                    </template>
                </WorkflowNavigationTitle>

                <!-- Runtime Settings Panel -->
                <div v-if="showRuntimeSettingsPanel" class="workflow-runtime-settings-panel p-3 rounded-bottom">
                    <!-- Send to new history -->
                    <div class="settings-row">
                        <GCheckbox id="send-to-new-history" v-model="sendToNewHistory" switch>
                            Send results to a new history
                            <HelpText uri="galaxy.workflows.runtimeSettings.sendToNewHistory" info-icon />
                        </GCheckbox>
                        <div v-if="sendToNewHistory" class="settings-detail">
                            <BFormInput
                                v-model="newHistoryName"
                                size="sm"
                                placeholder="New history name"
                                class="history-name-input" />
                        </div>
                    </div>

                    <!-- Use cached jobs -->
                    <div class="settings-row">
                        <GCheckbox v-model="useCachedJobs" switch>
                            Re-use jobs with identical parameters
                            <HelpText uri="galaxy.workflows.runtimeSettings.useCachedJobs" info-icon />
                        </GCheckbox>
                    </div>

                    <!-- Send notification -->
                    <div v-if="isConfigLoaded && config.enable_notification_system" class="settings-row">
                        <GCheckbox
                            v-model="sendNotificationOnComplete"
                            switch
                            data-test-id="send-notification-checkbox">
                            Notify me when complete
                            <HelpText uri="galaxy.workflows.runtimeSettings.sendNotification" info-icon />
                        </GCheckbox>
                    </div>

                    <!-- Export on completion -->
                    <div v-if="hasWritableFileSources" class="settings-row">
                        <GCheckbox :key="exportCheckboxKey" v-model="exportEnabled" switch>
                            Export results when complete
                            <HelpText uri="galaxy.workflows.runtimeSettings.exportOnComplete" info-icon />
                        </GCheckbox>
                        <div v-if="exportOnCompleteConfig" class="settings-detail">
                            <span class="export-summary">
                                <span class="text-muted">
                                    {{ exportOnCompleteConfig.target_uri.split("/").pop() }}
                                </span>
                                <GButton
                                    tooltip
                                    transparent
                                    color="blue"
                                    size="small"
                                    title="Edit export configuration"
                                    @click="showExportWizard = true">
                                    <span class="fa fa-edit" />
                                </GButton>
                            </span>
                        </div>
                    </div>

                    <!-- Storage options -->
                    <template v-if="isConfigLoaded && config.object_store_allows_id_selection">
                        <div class="settings-row">
                            <GCheckbox v-model="splitObjectStore" switch>
                                Send outputs and intermediate to different storage
                                <HelpText uri="galaxy.workflows.runtimeSettings.splitObjectStore" info-icon />
                            </GCheckbox>
                        </div>
                        <div class="settings-row">
                            <WorkflowStorageConfiguration
                                :split-object-store="splitObjectStore"
                                :invocation-preferred-object-store-id="preferredObjectStoreId"
                                :invocation-preferred-intermediate-object-store-id="preferredIntermediateObjectStoreId"
                                @updated="onStorageUpdate" />
                        </div>
                    </template>

                    <!-- Expanded form link -->
                    <div class="settings-row mt-2 pt-2 border-top">
                        <GButton
                            tooltip
                            transparent
                            color="blue"
                            size="small"
                            class="workflow-expand-form-link"
                            title="Switch to the legacy workflow form"
                            @click="$emit('showAdvanced')">
                            Expanded workflow form <FontAwesomeIcon :icon="faArrowRight" />
                        </GButton>
                    </div>
                </div>
            </div>
        </div>

        <WorkflowAnnotation
            :workflow-id="model.runData.workflow_id"
            :history-id="model.historyId"
            show-details
            :hide-hr="Boolean(showRightPanel)" />

        <WorkflowCredentials v-if="credentialTools?.length" :tool-identifiers="credentialTools" />

        <div class="overflow-auto h-100">
            <div class="d-flex h-100">
                <div
                    :class="showRightPanel ? 'w-50 flex-grow-1' : 'w-100'"
                    :style="{ 'overflow-y': 'auto', 'overflow-x': 'hidden' }">
                    <div v-if="showRightPanel" class="ui-form-header-underlay sticky-top" />
                    <Heading v-if="showRightPanel" class="sticky-top" h2 separator bold size="sm"> Parameters </Heading>
                    <GOverlay :show="changingCurrentHistory" no-fade :opacity="0.5">
                        <template v-slot:overlay>
                            <LoadingSpan message="Changing your current history" />
                        </template>
                        <FormDisplay
                            :inputs="formInputs"
                            :reject-empty-required-inputs="true"
                            :sync-with-graph="showGraph"
                            :active-node-id="computedActiveNodeId"
                            workflow-run
                            :steps-not-matching-request="stepsNotMatchingRequest"
                            @on-change="onChange"
                            @on-validation="onValidation"
                            @load-more="onLoadMore"
                            @search-change="onSearchChange"
                            @stop-flagging="checkInputMatching = false"
                            @update:active-node-id="updateActiveNodeId" />
                    </GOverlay>
                    <div class="workflow-run-step-parameters mt-3 mb-3" data-description="workflow run step parameters">
                        <Heading h2 separator bold size="sm">Step parameters ({{ exposedLeaves.length }})</Heading>
                        <GAlert
                            v-if="droppedStepParams.length"
                            variant="warning"
                            show
                            dismissible
                            data-description="dropped step parameters"
                            @dismissed="droppedStepParams = []">
                            These step parameters can't be set from this form and will not be sent:
                            <ul class="mb-0">
                                <li v-for="dropped in droppedStepParams" :key="dropped.key">
                                    <code>{{ dropped.key }}</code> - {{ dropped.reason }}
                                </li>
                            </ul>
                        </GAlert>
                        <p v-if="!exposedLeaves.length" class="text-muted small mb-2">
                            All tool steps use the workflow's saved settings. Add a step parameter to change one for
                            this run.
                        </p>
                        <div
                            v-for="leaf in exposedLeaves"
                            :key="leaf.key"
                            class="card mb-2 step-parameter-card"
                            :data-exposure-key="leaf.key">
                            <div class="card-header d-flex align-items-center py-1 px-2">
                                <span class="flex-grow-1 small">{{ (leaf.path || []).slice(0, -1).join(" › ") }}</span>
                                <span class="small text-muted mr-2">
                                    {{ isRerun ? "original run" : "saved" }}: {{ displayValue(leaf.input.value) }}
                                </span>
                                <GButton
                                    transparent
                                    size="small"
                                    color="grey"
                                    tooltip
                                    title="Remove - use the workflow's saved value"
                                    data-description="remove step parameter"
                                    @click="removeStepParam(leaf.key || '')">
                                    <FontAwesomeIcon :icon="faTimes" fixed-width />
                                </GButton>
                            </div>
                            <div class="card-body p-2">
                                <FormDisplay
                                    :inputs="stepParamInputs.get(leaf.key || '') || []"
                                    @on-change="onStepParamChange" />
                            </div>
                        </div>
                        <GButton
                            outline
                            size="small"
                            color="blue"
                            data-description="add step parameter"
                            @click="showStepParameterPicker = true">
                            <FontAwesomeIcon :icon="faPlus" fixed-width /> Add step parameter
                        </GButton>
                        <StepParameterPicker
                            v-model:show="showStepParameterPicker"
                            :tree="stepParameterTree"
                            :exposed-keys="exposedKeys"
                            @add="addStepParams" />
                    </div>
                </div>
                <div v-if="showRightPanel" class="h-100 w-50 d-flex flex-shrink-0">
                    <WorkflowRunGraph
                        v-if="isConfigLoaded && showGraph"
                        :workflow-id="model.workflowId"
                        :step-validation="stepValidation || undefined"
                        :stored-id="model.runData.workflow_id"
                        :version="model.runData.version"
                        :inputs="formData"
                        :form-inputs="formInputs" />
                    <div v-else-if="showHelp" class="d-flex flex-column">
                        <Heading class="sticky-top" h2 separator bold size="sm"> Help </Heading>
                        <WorkflowHelpDisplay :workflow="workflow" :loading="workflowLoading" />
                    </div>
                </div>
            </div>
        </div>

        <GModal
            v-model:show="showExportWizard"
            title="Configure Export on Completion"
            size="medium"
            @close="onExportWizardCancel">
            <ExportOnCompleteWizard
                :initial-config="exportOnCompleteConfig || undefined"
                @configured="onExportConfigured"
                @cancel="onExportWizardCancel" />
        </GModal>
    </div>
</template>

<style scoped lang="scss">
@import "@/style/scss/theme/blue.scss";

.workflow-runtime-settings-panel {
    background-color: $brand-light;
    border-left: 1px solid $gray-200;
    border-right: 1px solid $gray-200;
    border-bottom: 1px solid $gray-200;
    // Fade only: a transform or height animation moves the toggles while the
    // panel is appearing, so a click that starts on a row can land on another.
    animation: fadeIn 0.2s ease-in-out;
}

.settings-row {
    padding: 0.4rem 0;
    position: relative;

    &:first-child {
        padding-top: 0;
    }

    // Ensure popovers from this row appear above subsequent rows
    &:hover {
        z-index: 10;
    }
}

.settings-detail {
    margin-left: 2.5rem;
    margin-top: 0.25rem;
}

.history-name-input {
    max-width: 300px;
}

.export-summary {
    display: inline-flex;
    align-items: center;
    gap: 0.5rem;
    font-size: 0.9em;
}

@keyframes fadeIn {
    from {
        opacity: 0;
    }
    to {
        opacity: 1;
    }
}
</style>
