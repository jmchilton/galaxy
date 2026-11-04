<script setup lang="ts">
import { faSignOutAlt } from "@fortawesome/free-solid-svg-icons";
import { FontAwesomeIcon } from "@fortawesome/vue-fontawesome";

import type { EmbeddedOutput } from "./useEmbeddedOutputs";

import InvocationOutputSnapshot from "./InvocationOutputSnapshot.vue";

defineProps<{
    embedded: EmbeddedOutput[];
}>();

/** Straight connector from the middle of the source step's right edge to the card's header */
function connectorPath({ stepRect, rect }: EmbeddedOutput) {
    return `M ${stepRect.x + stepRect.width} ${stepRect.y + stepRect.height / 2} L ${rect.x} ${rect.y + 20}`;
}
</script>

<template>
    <!-- static snapshots: the same outputs are reachable from the step details, so keep them out of the tab order -->
    <div class="embedded-outputs" inert>
        <svg class="embedded-output-connectors">
            <path
                v-for="output in embedded"
                :key="output.key"
                data-description="invocation embedded output connector"
                :data-output-label="output.label"
                :d="connectorPath(output)" />
        </svg>
        <div
            v-for="output in embedded"
            :key="output.key"
            class="embedded-output card"
            data-description="invocation embedded output"
            :data-output-label="output.label"
            :style="{
                left: `${output.rect.x}px`,
                top: `${output.rect.y}px`,
                width: `${output.rect.width}px`,
                height: `${output.rect.height}px`,
            }">
            <div class="card-header py-1 px-2 embedded-output-header">
                <FontAwesomeIcon :icon="faSignOutAlt" fixed-width />
                <span class="font-weight-bold">{{ output.label }}</span>
            </div>
            <InvocationOutputSnapshot class="embedded-output-body" :item="output.item" :step="output.step" />
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
    // over the cards' halos, so each connector still meets its card
    z-index: 101;

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
    // a static snapshot: dragging and zooming over it move the graph, as anywhere else on the canvas
    pointer-events: none;
    border: 2px solid $brand-primary;
    // edges keep their routes and pass under cards; a halo shows they pass under, rather than end at, a card
    box-shadow: 0 0 0 5px var(--background-color);
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
    min-height: 0;

    // inset like the dataset and collection previews beside it, rather than against the card's border
    :deep(.invocation-output-not-ready) {
        padding: 0.25rem 0.5rem;
    }
}
</style>
