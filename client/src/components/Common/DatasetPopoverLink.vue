<script setup lang="ts">
import ItemPopoverLink from "./ItemPopoverLink.vue";

defineProps<{
    datasetId: string;
}>();
</script>

<template>
    <div>
        <ItemPopoverLink :item-id="datasetId" item-src="hda" link-class="text-monospace" />
    </div>
</template>
