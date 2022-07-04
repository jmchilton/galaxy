<template>
    <div>
        <div>
            <span v-localize>{{ what }}</span>
            <span class="display-os-by-name" v-if="storageInfo.name">
                a Galaxy <object-store-restriction-span :is-private="isPrivate" /> object store named
                <b>{{ storageInfo.name }}</b>
            </span>
            <span class="display-os-by-id" v-else-if="storageInfo.object_store_id">
                a Galaxy <object-store-restriction-span :is-private="isPrivate" /> object store with id
                <b>{{ storageInfo.object_store_id }}</b>
            </span>
            <span class="display-os-default" v-else>
                the default configured Galaxy <object-store-restriction-span :is-private="isPrivate" /> object store </span
            >.
        </div>
        <QuotaSourceUsageProvider
            :quotaSourceLabel="quotaSourceLabel"
            v-if="storageInfo.quota && storageInfo.quota.enabled"
            v-slot="{ result: quotaUsage, loading: isLoadingUsage }">
            <b-spinner v-if="isLoadingUsage" />
            <QuotaUsageBar v-else-if="quotaUsage" :quota-usage="quotaUsage" :embedded="true" />
        </QuotaSourceUsageProvider>
        <div v-else>Galaxy has no quota configured fo this object store.</div>
        <div v-html="descriptionRendered"></div>
    </div>
</template>

<script>
import MarkdownIt from "markdown-it";
import ObjectStoreRestrictionSpan from "./ObjectStoreRestrictionSpan";
import QuotaUsageBar from "components/User/DiskUsage/Quota/QuotaUsageBar";
import { QuotaSourceUsageProvider } from "components/User/DiskUsage/Quota/QuotaUsageProvider";

export default {
    components: {
        ObjectStoreRestrictionSpan,
        QuotaSourceUsageProvider,
        QuotaUsageBar,
    },
    props: {
        storageInfo: {
            type: Object,
            required: true,
        },
        what: {
            type: String,
            required: true,
        },
    },
    computed: {
        quotaSourceLabel() {
            return this.storageInfo.quota?.source;
        },
        descriptionRendered() {
            const description = this.storageInfo.description;
            let descriptionRendered;
            if (description) {
                descriptionRendered = MarkdownIt({ html: true }).render(description);
            } else {
                descriptionRendered = null;
            }
            return descriptionRendered;
        },
        isPrivate() {
            return this.storageInfo.private;
        },
    },
};
</script>
