<script setup lang="ts">
import { computed } from "vue";

import { getAppRoot } from "@/onload/loadConfig";

interface Props {
    datasetId: string;
    page?: string | number;
}

const props = withDefaults(defineProps<Props>(), {
    page: 1,
});

// Embed the PDF at the requested page with the viewer chrome hidden, so a single
// figure page reads as a flush figure rather than a full PDF viewer. The baked
// report rasterizes the same page server-side.
const pdfUrl = computed(() => {
    // Clamp to a 1-based page so the live embed matches the server's page rasterization
    // (which also floors to a 1-based page); never emit 0/negative/fractional.
    const pageNumber = Math.max(1, Math.floor(Number(props.page)) || 1);
    const display = `${getAppRoot()}dataset/display?dataset_id=${props.datasetId}`;
    return `${display}#page=${pageNumber}&toolbar=0&navpanes=0&view=FitH`;
});
</script>

<template>
    <div class="w-100">
        <embed :src="pdfUrl" type="application/pdf" class="pdf-embed" />
    </div>
</template>

<style lang="scss" scoped>
.pdf-embed {
    width: 100%;
    min-height: 600px;
}
</style>
