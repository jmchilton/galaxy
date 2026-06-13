<script setup lang="ts">
import { computedAsync } from "@vueuse/core";
import { BAlert, BImg } from "bootstrap-vue";
import { computed, ref } from "vue";

import { type PathDestination, useDatasetPathDestination } from "@/composables/datasetPathDestination";
import { getAppRoot } from "@/onload/loadConfig";

interface Props {
    historyDatasetId: string;
    path?: string;
    allowSizeToggle?: boolean;
}

const { datasetPathDestination } = useDatasetPathDestination();

const props = withDefaults(defineProps<Props>(), {
    allowSizeToggle: false,
});

const pathDestination = computedAsync<PathDestination | null>(async () => {
    return await datasetPathDestination.value(props.historyDatasetId, props.path);
}, null);

const imageUrl = computed(() => {
    if (props.path === undefined || props.path === "undefined") {
        return `${getAppRoot()}dataset/display?dataset_id=${props.historyDatasetId}`;
    }
    return pathDestination.value?.fileLink;
});

const contentType = computedAsync(async () => {
    if (!imageUrl.value) {
        return null;
    }
    const res = await fetch(imageUrl.value);
    const buff = await res.blob();
    return buff.type;
    // Optimistic default: assume an image until the fetch resolves the type.
}, "image/");

const isImage = computed(() => (contentType.value ?? "").startsWith("image/"));
// PDF-emitting tools (R volcano/DESeq2 plots, etc.) are displayed inline via the
// browser's native viewer; the baked report/export rasterizes them server-side.
const isPdf = computed(() => contentType.value === "application/pdf");

const isFluid = ref(true);

const toggleFluid = () => {
    isFluid.value = !isFluid.value;
};
</script>

<template>
    <div v-if="imageUrl" class="w-100">
        <div
            v-if="isImage"
            class="image-wrapper"
            :class="{ interactive: props.allowSizeToggle }"
            @click="props.allowSizeToggle ? toggleFluid() : null">
            <BImg :src="imageUrl" :fluid="isFluid" :class="{ 'cursor-pointer': props.allowSizeToggle }" />
            <div v-if="props.allowSizeToggle" class="size-hint">
                <small class="text-white">{{ isFluid ? "Click for actual size" : "Click to fit width" }}</small>
            </div>
        </div>
        <embed v-else-if="isPdf" :src="imageUrl" type="application/pdf" class="pdf-embed" />
        <BAlert v-else variant="warning" show> This dataset does not appear to be an image: {{ imageUrl }}. </BAlert>
    </div>
    <BAlert v-else variant="warning" show>Image not found: {{ imageUrl }}.</BAlert>
</template>

<style lang="scss" scoped>
.image-wrapper {
    position: relative;
    display: inline-block;
}

.pdf-embed {
    width: 100%;
    min-height: 600px;
}

.cursor-pointer {
    cursor: pointer;
    transition: transform 0.2s ease;
}

.interactive .cursor-pointer:hover {
    transform: scale(1.01);
}

.size-hint {
    position: absolute;
    bottom: 8px;
    right: 8px;
    background: rgba(0, 0, 0, 0.7);
    color: white;
    padding: 4px 8px;
    border-radius: 4px;
    opacity: 0;
    transition: opacity 0.2s ease;
    pointer-events: none;

    .image-wrapper:hover & {
        opacity: 1;
    }
}
</style>
