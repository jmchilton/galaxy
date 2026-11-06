<script setup lang="ts">
import { computed } from "vue";

import GPagination from "@/components/BaseComponents/GPagination.vue";

defineOptions({
    // Under @vue/compat, keep v-model on modelValue instead of Vue 2's value/input
    compatConfig: { COMPONENT_V_MODEL: false },
});

interface Props {
    /** The v-model value: the index of the shown job, starting at 0 */
    modelValue: number;
    jobCount: number;
}

const props = defineProps<Props>();

const emit = defineEmits<{
    (e: "update:modelValue", index: number): void;
}>();

const page = computed<number>({
    get: () => props.modelValue + 1,
    set: (value: number) => emit("update:modelValue", value - 1),
});
</script>

<template>
    <GPagination
        v-if="props.jobCount > 1"
        v-model="page"
        :total-rows="props.jobCount"
        :per-page="1"
        size="small"
        :limit="3"
        first-number
        last-number
        hide-goto-end-buttons
        class="job-pager unselectable" />
</template>

<style scoped>
.job-pager {
    margin-bottom: 0;
}
</style>
