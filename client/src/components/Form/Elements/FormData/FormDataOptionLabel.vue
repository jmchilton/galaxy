<script setup lang="ts">
import { computed } from "vue";

import localize from "@/utils/localization";

import { mapOverUnit } from "./collectionMatch";

const props = defineProps<{
    label: string;
    /** Set for options the tool would map over; the marker names what each job receives */
    mapOverType?: string | null;
}>();

const marker = computed(() =>
    props.mapOverType ? `${localize("one job per")} ${localize(mapOverUnit(props.mapOverType))}` : undefined,
);
</script>

<template>
    <span>{{ props.label }}</span>
    <span v-if="marker" class="form-data-map-over-marker">{{ marker }}</span>
</template>

<style scoped lang="scss">
// inherits the option's color so it stays readable on highlighted options
.form-data-map-over-marker {
    margin-left: 0.5rem;
    padding: 0 0.3rem;
    border: 1px solid currentColor;
    border-radius: 0.25rem;
    font-size: 0.75rem;
    white-space: nowrap;
    opacity: 0.8;
}
</style>
