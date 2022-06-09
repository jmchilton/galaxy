<template>
    <div class="quota-usage-bar mx-auto" :class="{ 'w-75': !embedded, 'my-5': !embedded, 'my-1': embedded }">
        <component :is="sourceTag" v-if="!isDefaultQuota" class="quota-storage-source">
            <span class="storage-source-label">
                <b>{{ quotaUsage.sourceLabel }}</b>
            </span>
            {{ storageSourceText }}
        </component>
        <component :is="usageTag">
            <b>{{ quotaUsage.niceTotalDiskUsage }}</b>
            <span v-if="quotaHasLimit"> of {{ quotaUsage.niceQuota }}</span> used
        </component>
        <span v-if="quotaHasLimit" class="quota-percent-text">
            {{ quotaUsage.quotaPercent }}{{ percentOfDiskQuotaUsedText }}
        </span>
        <b-progress
            v-if="quotaHasLimit || !embedded"
            :value="quotaUsage.quotaPercent"
            :variant="progressVariant"
            max="100" />
    </div>
</template>

<script>
import _l from "utils/localization";
import { DEFAULT_QUOTA_SOURCE_LABEL } from "./model/QuotaUsage";

export default {
    props: {
        quotaUsage: {
            type: Object,
            required: true,
        },
        // If this is embedded in DatasetStorage or more intricate components like
        // that - shrink everything and avoid h2/h3 (component already has those).
        embedded: {
            type: Boolean,
            default: false,
        },
    },
    data() {
        return {
            storageSourceText: _l("storage source"),
            percentOfDiskQuotaUsedText: _l("% of disk quota used"),
        };
    },
    computed: {
        /** @returns {Boolean} */
        isDefaultQuota() {
            return this.quotaUsage.sourceLabel === DEFAULT_QUOTA_SOURCE_LABEL;
        },
        /** @returns {Boolean} */
        quotaHasLimit() {
            return !this.quotaUsage.isUnlimited;
        },
        /** @returns {String} */
        progressVariant() {
            const percent = this.quotaUsage.quotaPercent;
            if (percent < 50) {
                return "success";
            } else if (percent >= 50 && percent < 80) {
                return "primary";
            } else if (percent >= 80 && percent < 95) {
                return "warning";
            }
            return "danger";
        },
        /** @returns {String} */
        sourceTag() {
            return this.embedded ? "div" : "h2";
        },
        usageTag() {
            return this.embedded ? "div" : "h3";
        },
    },
};
</script>
