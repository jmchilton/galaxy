<script setup lang="ts">
import { faInfoCircle } from "@fortawesome/free-solid-svg-icons";
import { FontAwesomeIcon } from "@fortawesome/vue-fontawesome";
import { computed } from "vue";

import type { ToolFormJobExpansion } from "@/api/tools";
import type { FormInputNode } from "@/components/Form/composables/useFormState";

import { jobCountNotices } from "./jobCount";

import GAlert from "@/components/BaseComponents/GAlert.vue";

const props = defineProps<{
    jobExpansion?: ToolFormJobExpansion;
    inputs?: FormInputNode[];
    remapping?: boolean;
}>();

const notices = computed(() => jobCountNotices(props.jobExpansion, props.inputs, props.remapping));
const status = computed(() => notices.value.find((n) => n.variant !== "warning"));
const warnings = computed(() => notices.value.filter((n) => n.variant === "warning"));
</script>

<template>
    <div class="tool-form-job-count">
        <!-- Always mounted so screen readers announce count changes. -->
        <div role="status" aria-live="polite" aria-atomic="true">
            <div
                v-if="status"
                :class="status.variant === 'info' ? 'text-info' : 'text-muted'"
                :data-job-count-notice="status.kind">
                <FontAwesomeIcon :icon="faInfoCircle" aria-hidden="true" />
                {{ status.text }}
                <div v-if="status.detail" class="small text-muted">{{ status.detail }}</div>
            </div>
        </div>
        <GAlert
            v-for="warning in warnings"
            :key="warning.kind"
            variant="warning"
            class="mt-2 mb-0"
            :data-job-count-notice="warning.kind">
            {{ warning.text }}
        </GAlert>
    </div>
</template>
