<template>
    <ConfigProvider v-slot="{ config }">
        <CurrentUser v-slot="{ user }">
            <div class="history-size my-1 d-flex justify-content-between">
                <b-button
                    v-if="config.object_store_allows_id_selection"
                    :id="`history-storage-${history.id}`"
                    v-b-tooltip.hover
                    variant="link"
                    size="sm"
                    class="rounded-0 text-decoration-none"
                    @click="showPreferredObjectStoreModal = true">
                    <icon icon="database" />
                    <span>{{ history.size | niceFileSize }}</span>
                </b-button>
                <b-button
                    v-else
                    v-b-tooltip.hover
                    title="Access Dashboard"
                    variant="link"
                    size="sm"
                    class="rounded-0 text-decoration-none"
                    @click="onDashboard">
                    <icon icon="database" />
                    <span>{{ history.size | niceFileSize }}</span>
                </b-button>
                <HistoryTargetPreferredObjectStorePopover
                    :history-id="history.id"
                    :history-preferred-object-store-id="historyPreferredObjectStoreId"
                    :user="user">
                </HistoryTargetPreferredObjectStorePopover>
                <b-button-group>
                    <b-button
                        v-b-tooltip.hover
                        title="Show active"
                        variant="link"
                        size="sm"
                        class="rounded-0 text-decoration-none"
                        @click="setFilter('')">
                        <span class="fa fa-map-marker" />
                        <span>{{ history.contents_active.active }}</span>
                    </b-button>
                    <b-button
                        v-if="history.contents_active.deleted"
                        v-b-tooltip.hover
                        title="Show deleted"
                        variant="link"
                        size="sm"
                        class="rounded-0 text-decoration-none"
                        @click="setFilter('deleted:true')">
                        <icon icon="trash" />
                        <span>{{ history.contents_active.deleted }}</span>
                    </b-button>
                    <b-button
                        v-if="history.contents_active.hidden"
                        v-b-tooltip.hover
                        title="Show hidden"
                        variant="link"
                        size="sm"
                        class="rounded-0 text-decoration-none"
                        @click="setFilter('visible:false')">
                        <icon icon="eye-slash" />
                        <span>{{ history.contents_active.hidden }}</span>
                    </b-button>
                    <b-button
                        v-b-tooltip.hover
                        :title="'Last refreshed ' + diffToNow"
                        variant="link"
                        size="sm"
                        class="rounded-0 text-decoration-none"
                        @click="reloadContents()">
                        <span :class="reloadButtonCls" />
                    </b-button>
                </b-button-group>
                <b-modal
                    title="History Preferred Object Store"
                    v-model="showPreferredObjectStoreModal"
                    modal-class="history-preferred-object-store-modal"
                    title-tag="h3"
                    size="sm"
                    hide-footer>
                    <HistorySelectPreferredObjectStore
                        :user-preferred-object-store-id="user.preferred_object_store_id"
                        :history="history"
                        :root="root"
                        @updated="onUpdatePreferredObjectStoreId" />
                </b-modal>
            </div>
        </CurrentUser>
    </ConfigProvider>
</template>

<script>
import { backboneRoute } from "components/plugins/legacyNavigation";
import prettyBytes from "pretty-bytes";
import { formatDistanceToNowStrict } from "date-fns";
import ConfigProvider from "components/providers/ConfigProvider";
import CurrentUser from "components/providers/CurrentUser";
import HistorySelectPreferredObjectStore from "./HistorySelectPreferredObjectStore";
import HistoryTargetPreferredObjectStorePopover from "./HistoryTargetPreferredObjectStorePopover";
import { getAppRoot } from "onload/loadConfig";

export default {
    components: {
        ConfigProvider,
        CurrentUser,
        HistoryTargetPreferredObjectStorePopover,
        HistorySelectPreferredObjectStore,
    },
    filters: {
        niceFileSize(rawSize = 0) {
            return prettyBytes(rawSize);
        },
    },
    props: {
        history: { type: Object, required: true },
        lastChecked: { type: Date, default: null },
    },
    data() {
        return {
            diffToNow: 0,
            reloadButtonCls: "fa fa-sync",
            showPreferredObjectStoreModal: false,
            historyPreferredObjectStoreId: this.history.preferred_object_store_id,
            root: getAppRoot(),
        };
    },
    mounted() {
        this.updateTime();
        // update every second
        setInterval(this.updateTime.bind(this), 1000);
    },
    methods: {
        onDashboard() {
            backboneRoute("/storage");
        },
        setFilter(newFilterText) {
            this.$emit("update:filter-text", newFilterText);
        },
        updateTime() {
            this.diffToNow = formatDistanceToNowStrict(this.lastChecked, { addSuffix: true, includeSeconds: true });
        },
        async reloadContents() {
            this.$emit("reloadContents");
            this.reloadButtonCls = "fa fa-sync fa-spin";
            setTimeout(() => {
                this.reloadButtonCls = "fa fa-sync";
            }, 1000);
        },
        onUpdatePreferredObjectStoreId(preferredObjectStoreId) {
            this.showPreferredObjectStoreModal = false;
            // ideally this would be pushed back to the history object somehow
            // and tracked there... but for now this is only component using
            // this information.
            this.historyPreferredObjectStoreId = preferredObjectStoreId;
        },
    },
};
</script>
