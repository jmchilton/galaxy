<script setup lang="ts">
import { faSignOutAlt } from "@fortawesome/free-solid-svg-icons";
import { FontAwesomeIcon } from "@fortawesome/vue-fontawesome";
import { computed } from "vue";

import type { GraphStep } from "@/composables/useInvocationGraph";
import { useWorkflowStores } from "@/composables/workflowStores";

import type { EmbeddedOutput } from "./useEmbeddedOutputs";

import InvocationOutputPreview from "./InvocationOutputPreview.vue";

const props = defineProps<{
    storeId: string;
    embedded: EmbeddedOutput[];
    steps: Record<string, GraphStep>;
}>();

const { stateStore } = useWorkflowStores(props.storeId);

/** Straight connector from the source step's right edge to the embedded node's left/top edge */
const connectors = computed(() =>
    props.embedded.flatMap((output) => {
        const step = props.steps[output.sourceId];
        const measured = stateStore.stepPosition[output.sourceId];
        if (!step?.position || !measured) {
            return [];
        }
        const besideSource = output.rect.x >= step.position.left + measured.width;
        const start = besideSource
            ? { x: step.position.left + measured.width, y: step.position.top + measured.height / 2 }
            : { x: step.position.left + measured.width / 2, y: step.position.top + measured.height };
        const end = besideSource
            ? { x: output.rect.x, y: output.rect.y + 20 }
            : { x: output.rect.x + 40, y: output.rect.y };
        return [{ key: output.key, path: `M ${start.x} ${start.y} L ${end.x} ${end.y}` }];
    }),
);
</script>

<template>
    <div class="embedded-outputs">
        <svg class="embedded-output-connectors">
            <path v-for="connector in connectors" :key="connector.key" :d="connector.path" />
        </svg>
        <!-- eslint-disable-next-line vuejs-accessibility/no-static-element-interactions -->
        <div
            v-for="output in embedded"
            :key="output.key"
            class="embedded-output card"
            data-description="invocation embedded output"
            :style="{
                left: `${output.rect.x}px`,
                top: `${output.rect.y}px`,
                width: `${output.rect.width}px`,
                height: `${output.rect.height}px`,
            }"
            @wheel.stop
            @pointerdown.stop>
            <div class="card-header py-1 px-2 embedded-output-header">
                <FontAwesomeIcon :icon="faSignOutAlt" fixed-width />
                <span class="font-weight-bold">{{ output.label }}</span>
            </div>
            <div class="embedded-output-body">
                <InvocationOutputPreview :item="output.item" />
            </div>
        </div>
    </div>
</template>

<style scoped lang="scss">
@import "@/style/scss/theme/blue.scss";

.embedded-outputs {
    position: absolute;
    top: 0;
    left: 0;
}

.embedded-output-connectors {
    position: absolute;
    overflow: visible;
    width: 1px;
    height: 1px;
    pointer-events: none;

    path {
        stroke: $brand-primary;
        stroke-width: 3;
        stroke-dasharray: 6 4;
        fill: none;
    }
}

.embedded-output {
    position: absolute;
    z-index: 100;
    border: 2px solid $brand-primary;
    display: flex;
    flex-direction: column;
    overflow: hidden;
}

.embedded-output-header {
    background: $brand-primary;
    color: $white;
}

.embedded-output-body {
    flex: 1;
    overflow: auto;
    font-size: 0.75rem;
}
</style>
