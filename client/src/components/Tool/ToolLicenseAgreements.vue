<script setup lang="ts">
import { faCheck } from "@fortawesome/free-solid-svg-icons";
import { FontAwesomeIcon } from "@fortawesome/vue-fontawesome";

import type { ToolLicenseAgreement } from "@/api/licenseAgreements";
import localize from "@/utils/localization";

import GCheckbox from "@/components/BaseComponents/GCheckbox.vue";
import Heading from "@/components/Common/Heading.vue";
import LicenseTerms from "@/components/License/LicenseTerms.vue";

interface Props {
    agreements: ToolLicenseAgreement[];
    /** Hashes of the agreements the user has affirmed for this submission. */
    affirmed: string[];
    /** Hashes of affirmed agreements the user wants remembered. */
    remembered: string[];
}

const props = defineProps<Props>();

const emit = defineEmits<{
    (e: "update:affirmed", value: string[]): void;
    (e: "update:remembered", value: string[]): void;
}>();

function toggle(values: string[], agreementHash: string, on: boolean): string[] {
    const others = values.filter((value) => value !== agreementHash);
    return on ? [...others, agreementHash] : others;
}

function onAffirm(agreement: ToolLicenseAgreement, affirmed: boolean) {
    emit("update:affirmed", toggle(props.affirmed, agreement.agreement_hash, affirmed));
    if (!affirmed) {
        emit("update:remembered", toggle(props.remembered, agreement.agreement_hash, false));
    }
}

function onRemember(agreement: ToolLicenseAgreement, remembered: boolean) {
    emit("update:remembered", toggle(props.remembered, agreement.agreement_hash, remembered));
}
</script>

<template>
    <div class="tool-license-agreements mt-2 mb-4" data-description="tool license agreements">
        <Heading v-localize h2 separator bold size="sm">License Agreements</Heading>
        <fieldset
            v-for="agreement in props.agreements"
            :key="agreement.agreement_hash"
            class="tool-license-agreement mb-3"
            :data-license-id="agreement.id">
            <legend class="h-text font-weight-bold">{{ agreement.label }}</legend>
            <div v-if="agreement.accepted" class="text-success" data-description="license accepted">
                <FontAwesomeIcon :icon="faCheck" />
                {{ localize("You have accepted this license agreement.") }}
            </div>
            <template v-else>
                <div>
                    <a v-if="agreement.url" :href="agreement.url" target="_blank" rel="noopener noreferrer">
                        {{ localize("About this license") }}
                    </a>
                    <LicenseTerms :license-id="agreement.id" :label="agreement.label" :terms="agreement.terms" />
                </div>
                <div class="mt-2">
                    <GCheckbox
                        :id="`license-affirm-${agreement.id}`"
                        :value="props.affirmed.includes(agreement.agreement_hash)"
                        @input="onAffirm(agreement, $event)">
                        {{ agreement.affirmation }}
                    </GCheckbox>
                </div>
                <div
                    v-if="agreement.binds === 'user'"
                    class="mt-1 ml-4"
                    :title="
                        props.affirmed.includes(agreement.agreement_hash)
                            ? undefined
                            : localize('Accept the agreement above to remember it.')
                    ">
                    <GCheckbox
                        :id="`license-remember-${agreement.id}`"
                        :value="props.remembered.includes(agreement.agreement_hash)"
                        :disabled="!props.affirmed.includes(agreement.agreement_hash)"
                        @input="onRemember(agreement, $event)">
                        {{ localize("Remember my acceptance - don't ask me again") }}
                    </GCheckbox>
                </div>
            </template>
        </fieldset>
    </div>
</template>

<style scoped>
.tool-license-agreement legend {
    font-size: inherit;
    width: auto;
    margin-bottom: 0.25rem;
}
</style>
