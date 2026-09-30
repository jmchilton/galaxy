<script setup lang="ts">
import { computed, ref } from "vue";

import localize from "@/utils/localization";

import GButton from "@/components/BaseComponents/GButton.vue";

interface Props {
    /** License agreement id, used for element ids and test selectors. */
    licenseId: string;
    label: string;
    terms: string;
}

const props = defineProps<Props>();

const shown = ref(false);
const termsId = computed(() => `license-terms-${props.licenseId}`);
</script>

<template>
    <span class="license-terms">
        <GButton
            size="small"
            outline
            :aria-expanded="shown ? 'true' : 'false'"
            :aria-controls="termsId"
            :data-test-id="`license-terms-toggle-${props.licenseId}`"
            @click="shown = !shown">
            {{ shown ? localize("Hide terms") : localize("View terms") }}
        </GButton>
        <pre
            v-if="shown"
            :id="termsId"
            class="license-terms-text mt-2 p-2"
            tabindex="0"
            role="region"
            :aria-label="`${props.label} ${localize('terms')}`"
            :data-test-id="`license-terms-${props.licenseId}`"
            >{{ props.terms }}</pre
        >
    </span>
</template>

<style scoped>
.license-terms-text {
    max-height: 20rem;
    overflow: auto;
    white-space: pre-wrap;
    border: 1px solid var(--border-color, #dee2e6);
}
</style>
