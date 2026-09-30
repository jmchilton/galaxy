<script setup lang="ts">
import { onMounted, ref } from "vue";

import {
    fetchLicenseAcceptances,
    type LicenseAcceptance,
    revokeLicenseAcceptance,
    type UserLicenseAcceptances,
} from "@/api/licenseAgreements";
import { useConfirmDialog } from "@/composables/confirmDialog";
import { Toast } from "@/composables/toast";
import localize from "@/utils/localization";
import { errorMessageAsString } from "@/utils/simple-error";

import GAlert from "@/components/BaseComponents/GAlert.vue";
import GButton from "@/components/BaseComponents/GButton.vue";
import BreadcrumbHeading from "@/components/Common/BreadcrumbHeading.vue";
import Heading from "@/components/Common/Heading.vue";
import LicenseTerms from "@/components/License/LicenseTerms.vue";
import LoadingSpan from "@/components/LoadingSpan.vue";
import UtcDate from "@/components/UtcDate.vue";

const breadcrumbItems = [{ title: "User Preferences", to: "/user" }, { title: "License Agreements" }];

const { confirm } = useConfirmDialog();

const acceptances = ref<UserLicenseAcceptances | null>(null);
const loading = ref(true);
const errorMessage = ref("");

async function load() {
    loading.value = true;
    try {
        acceptances.value = await fetchLicenseAcceptances(true);
        errorMessage.value = "";
    } catch (e) {
        errorMessage.value = errorMessageAsString(e);
    } finally {
        loading.value = false;
    }
}

async function revoke(acceptance: LicenseAcceptance) {
    const confirmed = await confirm(
        localize("Tools declaring this license agreement will ask you to accept it again."),
        { title: localize("Revoke License Agreement"), okText: localize("Revoke"), okColor: "red" },
    );
    if (!confirmed) {
        return;
    }
    try {
        await revokeLicenseAcceptance(acceptance.agreement.agreement_hash);
        Toast.success(localize("License agreement acceptance revoked."));
    } catch (e) {
        Toast.error(errorMessageAsString(e));
    }
    await load();
}

onMounted(load);
</script>

<template>
    <div class="license-agreements-management">
        <BreadcrumbHeading :items="breadcrumbItems" />
        <div class="mb-2">
            {{
                localize(
                    "License agreements you have accepted for tools, and a record of every acceptance and revocation.",
                )
            }}
        </div>
        <GAlert v-if="errorMessage" variant="danger">{{ errorMessage }}</GAlert>
        <LoadingSpan v-if="loading" :message="localize('Loading your license agreements')" />
        <template v-else-if="acceptances">
            <Heading h2 size="sm" separator>{{ localize("Accepted License Agreements") }}</Heading>
            <GAlert v-if="!acceptances.accepted.length" variant="info" data-description="no accepted licenses">
                {{ localize("You have not accepted any license agreements.") }}
            </GAlert>
            <div
                v-for="acceptance in acceptances.accepted"
                :key="acceptance.agreement.agreement_hash"
                class="license-acceptance mb-3"
                :data-license-id="acceptance.event.license_id"
                :data-agreement-hash="acceptance.agreement.agreement_hash">
                <div>
                    <strong>{{ acceptance.event.license_label }}</strong>
                    <span class="text-muted">
                        {{ acceptance.event.license_id }} ({{ localize("version") }}
                        {{ acceptance.event.license_version }}), {{ localize("accepted") }}
                        <UtcDate :date="acceptance.event.create_time" mode="elapsed" />
                    </span>
                </div>
                <div class="text-muted">{{ acceptance.agreement.affirmation }}</div>
                <div class="mt-1">
                    <LicenseTerms
                        :license-id="acceptance.event.license_id || acceptance.agreement.agreement_hash"
                        :label="acceptance.event.license_label || ''"
                        :terms="acceptance.agreement.terms" />
                    <GButton
                        size="small"
                        color="red"
                        :data-test-id="`license-revoke-${acceptance.event.license_id}`"
                        @click="revoke(acceptance)">
                        {{ localize("Revoke") }}
                    </GButton>
                </div>
            </div>

            <Heading h2 size="sm" separator>{{ localize("History") }}</Heading>
            <table class="table table-sm" data-description="license acceptance history">
                <thead>
                    <tr>
                        <th>{{ localize("When") }}</th>
                        <th>{{ localize("Action") }}</th>
                        <th>{{ localize("License Agreement") }}</th>
                        <th>{{ localize("Granted By") }}</th>
                        <th>{{ localize("Tool") }}</th>
                    </tr>
                </thead>
                <tbody>
                    <tr
                        v-for="event in acceptances.history || []"
                        :key="event.id"
                        class="license-acceptance-event"
                        :data-action="event.action">
                        <td><UtcDate :date="event.create_time" mode="pretty" /></td>
                        <td>{{ event.action === "accept" ? localize("Accepted") : localize("Revoked") }}</td>
                        <td>{{ event.license_label }} ({{ event.license_id }} {{ event.license_version }})</td>
                        <td>{{ event.granted_by === "admin" ? localize("Administrator") : localize("You") }}</td>
                        <td>{{ event.prompting_tool_id || "-" }}</td>
                    </tr>
                </tbody>
            </table>
        </template>
    </div>
</template>
