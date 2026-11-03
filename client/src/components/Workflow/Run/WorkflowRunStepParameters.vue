<script setup lang="ts">
import { faListUl, faTimes } from "@fortawesome/free-solid-svg-icons";
import { FontAwesomeIcon } from "@fortawesome/vue-fontawesome";
import { computed, markRaw, ref, watch } from "vue";

import {
    buildStepParameterOverrides,
    buildStepParameterTree,
    displayValue,
    type DroppedStepParameter,
    parseStepParameterOverridesArg,
    resolveStepParameterKeys,
    type RunStep,
    type StepParameterLeaf,
    type StepParameterOverrides,
    stepParameterOverrideValues,
    type ToolInput,
    typedParameterValue,
} from "./stepParameterTree";

import StepParameterPicker from "./StepParameterPicker.vue";
import GAlert from "@/components/BaseComponents/GAlert.vue";
import GButton from "@/components/BaseComponents/GButton.vue";
import Heading from "@/components/Common/Heading.vue";
import FormDisplay from "@/components/Form/FormDisplay.vue";

const props = withDefaults(
    defineProps<{
        /** Steps of the ``WorkflowRunModel`` of the workflow being run */
        steps: RunStep[];
        /** Overrides the invocation being rerun recorded, shown with their recorded values */
        rerunOverrides?: Record<string, unknown> | null;
        /** URL-encoded JSON ``step_parameter_overrides`` route argument; ``null`` leaves show without a preset */
        linkOverrides?: string;
        isRerun?: boolean;
    }>(),
    { rerunOverrides: null, linkOverrides: undefined, isRerun: false },
);

const emit = defineEmits<{
    (e: "update:overrides", overrides: StepParameterOverrides | null): void;
}>();

/** A chosen step parameter, with the one-input form that sets its value. */
interface StepParameterCard {
    leaf: StepParameterLeaf;
    /** Kept by identity: FormDisplay resyncs, dropping what was typed, when its inputs change. */
    inputs: [ToolInput];
    /** The form's value */
    value: unknown;
}

const tree = computed(() => buildStepParameterTree({ steps: props.steps }));
const showPicker = ref(false);
const cards = ref<StepParameterCard[]>([]);
const dropped = ref<DroppedStepParameter[]>([]);
const linkError = ref<string>();
const keys = computed(() => cards.value.map((card) => card.leaf.id));

const recorded = stepParameterOverrideValues(props.rerunOverrides);
const presets = new Map(recorded);
let cardCount = 0;

function newCard(leaf: StepParameterLeaf): StepParameterCard {
    const input = {
        ...JSON.parse(JSON.stringify(leaf.input)),
        name: `step_parameter_${cardCount++}`,
        label: leaf.label,
        flavor: undefined,
    };
    delete input.collapsible_value;
    delete input.collapsible_preview;
    const preset = presets.get(leaf.id);
    if (preset !== undefined && preset !== null) {
        input.value = preset;
    }
    return { leaf, inputs: markRaw([input]), value: input.value };
}

/** Show cards for ``wanted``, in workflow order, keeping the cards already shown for them. */
function showStepParameters(wanted: string[]) {
    const resolved = resolveStepParameterKeys(tree.value, wanted);
    dropped.value = [...dropped.value, ...resolved.dropped];
    const shown = new Map(cards.value.map((card) => [card.leaf.id, card]));
    cards.value = resolved.leaves.map((leaf) => shown.get(leaf.id) ?? newCard(leaf));
}

function removeStepParameter(card: StepParameterCard) {
    cards.value = cards.value.filter((other) => other !== card);
}

function onCardChange(card: StepParameterCard, data: Record<string, unknown>) {
    card.value = data[card.inputs[0].name];
}

function cardHint(leaf: StepParameterLeaf): string {
    if (props.isRerun && recorded.has(leaf.id)) {
        return `original run: ${displayValue({ ...leaf.input, value: recorded.get(leaf.id) }) ?? "(empty)"}`;
    }
    return `saved: ${leaf.value ?? "(empty)"}`;
}

const overrides = computed<StepParameterOverrides | null>(() => {
    if (!cards.value.length) {
        return null;
    }
    return buildStepParameterOverrides(
        cards.value.map(({ leaf, inputs: [input], value }) => ({
            stepPath: leaf.stepPath,
            paramPath: leaf.paramPath,
            value: typedParameterValue(input, value),
        })),
    );
});

watch(overrides, (value) => emit("update:overrides", value), { immediate: true });

{
    const link = parseStepParameterOverridesArg(props.linkOverrides);
    linkError.value = link.error;
    const linked = stepParameterOverrideValues(link.overrides);
    for (const [key, value] of linked) {
        if (value !== null) {
            presets.set(key, value);
        }
    }
    const initial = [...new Set([...recorded.keys(), ...linked.keys()])];
    if (initial.length) {
        showStepParameters(initial);
    }
}
</script>

<template>
    <div class="workflow-run-step-parameters mt-3 mb-3" data-description="workflow run step parameters">
        <Heading h2 separator bold size="sm">Step parameters ({{ cards.length }})</Heading>
        <GAlert v-if="linkError" variant="warning" show data-description="step parameter link error">
            {{ linkError }}
        </GAlert>
        <GAlert
            v-if="dropped.length"
            variant="warning"
            show
            dismissible
            data-description="dropped step parameters"
            @dismissed="dropped = []">
            These step parameters can't be set from this form and will not be sent:
            <ul class="mb-0">
                <li v-for="item in dropped" :key="item.key" :data-parameter-key="item.key">
                    {{ item.label }} - {{ item.reason }}
                </li>
            </ul>
        </GAlert>
        <p v-if="!cards.length" class="text-muted small mb-2">
            All tool steps use the workflow's saved settings. Choose step parameters to change some for this run.
        </p>
        <div
            v-for="card in cards"
            :key="card.leaf.id"
            class="card mb-2 step-parameter-card"
            data-description="step parameter card"
            :data-parameter-key="card.leaf.id">
            <div class="card-header d-flex align-items-center py-1 px-2">
                <span class="flex-grow-1 small">{{ card.leaf.path.slice(0, -1).join(" › ") }}</span>
                <span class="small text-muted mr-2">{{ cardHint(card.leaf) }}</span>
                <GButton
                    transparent
                    size="small"
                    color="grey"
                    tooltip
                    title="Remove - use the workflow's saved value"
                    data-description="remove step parameter"
                    @click="removeStepParameter(card)">
                    <FontAwesomeIcon :icon="faTimes" fixed-width />
                </GButton>
            </div>
            <div class="card-body p-2">
                <FormDisplay :inputs="card.inputs" @on-change="onCardChange(card, $event)" />
            </div>
        </div>
        <GButton outline size="small" color="blue" data-description="choose step parameters" @click="showPicker = true">
            <FontAwesomeIcon :icon="faListUl" fixed-width /> Choose step parameters
        </GButton>
        <StepParameterPicker v-model:show="showPicker" :tree="tree" :selected-keys="keys" @apply="showStepParameters" />
    </div>
</template>
