<script setup lang="ts">
import { faExclamation, faInfoCircle } from "@fortawesome/free-solid-svg-icons";
import { FontAwesomeIcon } from "@fortawesome/vue-fontawesome";

import localize from "@/utils/localization";

import { PROCESSING_HELP_TERMS, type ProcessingMode } from "./processingMode";

import HelpText from "@/components/Help/HelpText.vue";

defineProps<{
    mode: ProcessingMode;
}>();
</script>

<template>
    <div
        class="form-data-processing-hint"
        :class="mode.kind === 'batch' ? 'text-info' : 'text-muted'"
        :data-processing-mode="mode.kind">
        <template v-if="mode.kind === 'batch'">
            <FontAwesomeIcon :icon="faExclamation" />
            <span v-if="mode.source === 'collection'" class="ml-1">
                {{ localize("The selected") }}
                <code v-if="mode.collectionType">{{ mode.collectionType }}</code>
                {{ localize("collection will be") }}
                <HelpText :text="localize('mapped over')" :uri="PROCESSING_HELP_TERMS.mapOver" />
                {{ localize("this tool:") }}
                <template v-if="mode.mapOverType">
                    {{ localize("one job per") }} <code>{{ mode.mapOverType }}</code> {{ localize("element.") }}
                </template>
                <template v-else>{{ localize("one job per dataset.") }}</template>
            </span>
            <span v-else class="ml-1">
                {{ localize("Batch mode: one job will be run for each selected dataset.") }}
            </span>
        </template>
        <template v-else>
            <FontAwesomeIcon :icon="faInfoCircle" />
            <span class="ml-1">
                <template v-if="mode.source === 'datasets'">
                    {{ localize("All selected datasets will be") }}
                    <HelpText
                        :text="localize('processed together in a single job')"
                        :uri="PROCESSING_HELP_TERMS.reduction" />.
                </template>
                <template v-else>
                    {{ localize("The selected collection will be") }}
                    <HelpText
                        :text="localize('processed as a whole in a single job')"
                        :uri="PROCESSING_HELP_TERMS.reduction" />.
                </template>
                <HelpText
                    v-if="mode.canNest"
                    :text="
                        localize(mode.source === 'datasets' ? 'Need one job per dataset?' : 'Need one job per element?')
                    "
                    :uri="PROCESSING_HELP_TERMS.nestToMapOver" />
            </span>
        </template>
    </div>
</template>
