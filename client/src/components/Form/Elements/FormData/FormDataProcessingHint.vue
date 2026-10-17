<script setup lang="ts">
import { faExclamation, faInfoCircle } from "@fortawesome/free-solid-svg-icons";
import { FontAwesomeIcon } from "@fortawesome/vue-fontawesome";
import { computed } from "vue";

import { describeProcessingMode, type ProcessingMode } from "./processingMode";

import HelpText from "@/components/Help/HelpText.vue";

const props = defineProps<{
    mode: ProcessingMode;
}>();

const text = computed(() => describeProcessingMode(props.mode));
</script>

<template>
    <div
        class="form-data-processing-hint"
        :class="mode.kind === 'batch' ? 'text-info' : 'text-muted'"
        :data-processing-mode="mode.kind">
        <FontAwesomeIcon :icon="mode.kind === 'batch' ? faExclamation : faInfoCircle" />
        <span class="ml-1">
            {{ text.lead }}
            <code v-if="text.code">{{ text.code.type }}</code>
            {{ text.code?.after }}
            <HelpText :text="text.link.text" :uri="text.link.uri" />{{ text.tail }}
            <HelpText v-if="text.nest" :text="text.nest.text" :uri="text.nest.uri" />
        </span>
    </div>
</template>
