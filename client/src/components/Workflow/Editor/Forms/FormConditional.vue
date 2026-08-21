<script setup lang="ts">
import { computed } from "vue";

import { useConfirmDialog } from "@/composables/confirmDialog";
import { useWorkflowStores } from "@/composables/workflowStores";
import { connectedInputCanBeAbsent, presenceGateIsSpellable, type Step } from "@/stores/workflowStepStore";

import { presenceGateExpression } from "../modules/whenExpression";

import FormElement from "@/components/Form/FormElement.vue";

/** The gate the boolean mode writes; the `id: when` convention the IWC corpus uses. */
const BOOLEAN_GATE = "$(inputs.when)";

type GateMode = "none" | "boolean" | "presence" | "custom";

const emit = defineEmits<{
    (e: "onUpdateStep", id: number, value: Partial<Step>): void;
}>();
const props = defineProps<{
    step: Step;
}>();

const { stepStore } = useWorkflowStores();
const { confirm } = useConfirmDialog();

const connectedInputNames = computed(() => Object.keys(props.step.input_connections ?? {}));

const gateableInputs = computed(() =>
    connectedInputNames.value
        .filter((name) => connectedInputCanBeAbsent(props.step, name, stepStore))
        .filter((name) => presenceGateIsSpellable(props.step, name))
        .map((name) => [inputLabel(name), name]),
);

/** The input a presence gate written by this form addresses, if the gate is one of ours. */
const presenceGateInput = computed(() =>
    connectedInputNames.value.find((name) => props.step.when === presenceGateExpression(name)),
);

const mode = computed<GateMode>(() => {
    if (!props.step.when) {
        return "none";
    }
    if (props.step.when === BOOLEAN_GATE) {
        return "boolean";
    }
    return presenceGateInput.value ? "presence" : "custom";
});

const modeOptions = computed(() => {
    const options = [
        ["Always run this step", "none"],
        ["Run when a boolean parameter is true", "boolean"],
    ];
    if (gateableInputs.value.length > 0 || mode.value === "presence") {
        options.push(["Run when an input is provided", "presence"]);
    }
    if (mode.value === "custom") {
        options.push(["Custom expression", "custom"]);
    }
    return options;
});

function inputLabel(name: string): string {
    return props.step.inputs?.find((input) => input.name === name)?.label || name;
}

function onMode(newMode: GateMode) {
    if (newMode === mode.value) {
        return;
    }
    if (newMode === "none") {
        clearGate();
    } else if (newMode === "boolean") {
        emit("onUpdateStep", props.step.id, {
            when: BOOLEAN_GATE,
            input_connections: { ...(props.step.input_connections ?? {}), when: undefined },
        });
    } else if (newMode === "presence") {
        const firstGateable = gateableInputs.value[0];
        if (firstGateable) {
            onPresenceInput(firstGateable[1]!);
        }
    }
}

function onPresenceInput(inputName: string) {
    emit("onUpdateStep", props.step.id, { when: presenceGateExpression(inputName) });
}

async function clearGate() {
    if (mode.value === "custom") {
        const confirmed = await confirm(
            `This step runs only when ${props.step.when} is true. That condition was not written by this form and cannot be restored here.`,
            { title: "Remove this step's condition?", okText: "Remove" },
        );
        if (!confirmed) {
            return;
        }
    }
    emit("onUpdateStep", props.step.id, { when: undefined });
}
</script>

<template>
    <div>
        <FormElement
            id="__conditional"
            :value="mode"
            title="Conditionally skip step?"
            type="select"
            :options="modeOptions"
            help="Choose what decides whether this step runs. A skipped step produces no outputs; merge them with a fallback using a Pick Value step."
            @input="onMode" />
        <FormElement
            v-if="mode === 'presence'"
            id="__when_input"
            :value="presenceGateInput"
            title="Run only when this input is provided"
            type="select"
            :options="gateableInputs"
            help="The step is skipped when the connected input carries no dataset or value."
            @input="onPresenceInput" />
        <FormElement
            v-if="mode === 'custom'"
            id="__when"
            :value="step.when"
            title="Condition"
            type="text"
            :disabled="true"
            help="This step runs if the expression evaluates to true. Expressions written outside this form are shown but not edited here." />
    </div>
</template>
