<script setup lang="ts">
import { faExclamation, faInfoCircle } from "@fortawesome/free-solid-svg-icons";
import { FontAwesomeIcon } from "@fortawesome/vue-fontawesome";
import { computed } from "vue";

import { collectionTypeLabel } from "@/components/Collections/common/buildCollectionModal";
import localize from "@/utils/localization";

import { mapOverUnit, PROCESSING_HELP_TERMS, type ProcessingMode } from "./processingMode";

import HelpText from "@/components/Help/HelpText.vue";

const props = defineProps<{
    mode: ProcessingMode;
}>();

const selectedLabel = computed(() =>
    props.mode.kind === "batch" && props.mode.collectionType
        ? collectionTypeLabel(props.mode.collectionType)
        : undefined,
);

const jobUnit = computed(() => mapOverUnit(props.mode.kind === "batch" ? props.mode.mapOverType : undefined));

/** Sentence start before the help link, for hints without inline collection types */
const lead = computed(() => {
    const { mode } = props;
    if (mode.kind === "batch") {
        if (mode.source === "collection") {
            return localize("Each selected collection will be");
        }
        return localize(mode.hasSelection ? "Each selected dataset will be" : "Each dataset selected here will be");
    }
    if (mode.source === "collection") {
        if (mode.plural) {
            return localize("The selected collections will be");
        }
        return localize(mode.hasSelection ? "The selected collection will be" : "A collection selected here will be");
    }
    return localize(mode.hasSelection ? "All selected datasets will be" : "Datasets selected here will be");
});

const nestText = computed(() =>
    localize(props.mode.source === "datasets" ? "Need one job per dataset?" : "Need one job per element?"),
);
</script>

<template>
    <div
        class="form-data-processing-hint"
        :class="mode.kind === 'batch' ? 'text-info' : 'text-muted'"
        :data-processing-mode="mode.kind">
        <template v-if="mode.kind === 'batch'">
            <FontAwesomeIcon :icon="faExclamation" />
            <span v-if="mode.source === 'datasets' || mode.perItem" class="ml-1">
                {{ lead }}
                <HelpText :text="localize('run as a separate job')" :uri="PROCESSING_HELP_TERMS.mapOver" />,
                {{ localize("matched in order with other batch inputs.") }}
            </span>
            <span v-else class="ml-1">
                <template v-if="!mode.hasSelection">{{ localize("A collection selected here") }}</template>
                <template v-else-if="selectedLabel">{{ localize("The selected") }} {{ selectedLabel }}</template>
                <template v-else>
                    {{ localize("The selected") }} <code v-if="mode.collectionType">{{ mode.collectionType }}</code>
                    {{ localize("collection") }}
                </template>
                {{ localize("will be") }}
                <HelpText :text="localize('mapped over')" :uri="PROCESSING_HELP_TERMS.mapOver" />
                {{ localize("this tool: one job per") }} {{ localize(jobUnit) }}.
            </span>
        </template>
        <template v-else>
            <FontAwesomeIcon :icon="faInfoCircle" />
            <span class="ml-1">
                {{ lead }}
                <HelpText
                    :text="
                        localize(
                            mode.source === 'collection' && !mode.plural
                                ? 'processed as a whole in a single job'
                                : 'processed together in a single job',
                        )
                    "
                    :uri="PROCESSING_HELP_TERMS.reduction" />.
                <HelpText v-if="mode.canNest" :text="nestText" :uri="PROCESSING_HELP_TERMS.nestToMapOver" />
            </span>
        </template>
    </div>
</template>
