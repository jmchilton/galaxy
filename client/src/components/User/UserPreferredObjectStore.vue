<template>
    <b-row class="ml-3 mb-1">
        <i class="pref-icon pt-1 fa fa-lg fa-hdd" />
        <div class="pref-content pr-1">
            <a
                v-b-modal.modal-select-preferred-object-store
                id="select-preferred-object-store"
                href="javascript:void(0)"
                ><b v-localize>Preferred Object Store</b></a
            >
            <div v-localize class="form-text text-muted">
                Select a preferred default object store for the outputs of new jobs to be created in.
            </div>
            <b-modal
                id="modal-select-preferred-object-store"
                ref="modal"
                v-model="showModal"
                centered
                title="Preferred Object Store"
                :title-tag="titleTag"
                hide-footer
                static
                :size="modalSize"
                @show="resetModal"
                @hidden="resetModal">
                <loading-span v-if="loading" :message="loadingObjectStoreInfoMessage" />
                <div v-else>
                    <b-alert class="object-store-selection-error" v-if="error" variant="danger" show>
                        {{ error }}
                    </b-alert>
                    <b-row>
                        <b-col cols="7">
                            <b-button-group vertical size="lg" style="width: 100%">
                                <b-button
                                    id="no-preferred-object-store-button"
                                    :variant="variant(null)"
                                    class="preferred-object-store-select-button"
                                    data-object-store-id="__null__"
                                    @click="handleSubmit(null)"
                                    ><i v-localize>{{ galaxySelectionDefalutTitle }}</i></b-button
                                >
                                <b-button
                                    :variant="variant(object_store.object_store_id)"
                                    :id="`preferred-object-store-button-${object_store.object_store_id}`"
                                    v-for="object_store in objectStores"
                                    :key="object_store.object_store_id"
                                    class="preferred-object-store-select-button"
                                    :data-object-store-id="object_store.object_store_id"
                                    @click="handleSubmit(object_store.object_store_id)"
                                    >{{ object_store.name }}
                                    <ObjectStoreBadges :badges="object_store.badges" size="lg" :more-on-hover="false" />
                                    <ProvidedQuotaSourceUsageBar :objectStore="object_store" :compact="true">
                                    </ProvidedQuotaSourceUsageBar>
                                </b-button>
                            </b-button-group>
                        </b-col>
                        <b-col cols="5"
                            ><p style="width: 100%" v-localize>{{ whyIsSelectionPreferredText }}</p></b-col
                        >
                    </b-row>
                    <b-popover target="no-preferred-object-store-button" triggers="hover" :placement="popoverPlacement">
                        <template v-slot:title
                            ><span v-localize>{{ galaxySelectionDefalutTitle }}</span></template
                        >
                        <span v-localize>{{ galaxySelectionDefalutDescription }}</span>
                    </b-popover>
                    <b-popover
                        v-for="object_store in objectStores"
                        :key="object_store.object_store_id"
                        :target="`preferred-object-store-button-${object_store.object_store_id}`"
                        triggers="hover"
                        :placement="popoverPlacement">
                        <template v-slot:title>{{ object_store.name }}</template>
                        <DescribeObjectStore :what="newDatasetsDescription" :storage-info="object_store">
                        </DescribeObjectStore>
                    </b-popover>
                </div>
            </b-modal>
        </div>
    </b-row>
</template>

<script>
import axios from "axios";
import Vue from "vue";
import { BAlert, BPopover, BButton, BButtonGroup, BModal, BRow, VBModal } from "bootstrap-vue";
import selectionMixin from "components/ObjectStore/selectionMixin";

Vue.use(VBModal);

export default {
    components: {
        BPopover,
        BButton,
        BButtonGroup,
        BModal,
        BRow,
        BAlert,
    },
    mixins: [selectionMixin],
    props: {
        userId: {
            type: String,
            required: true,
        },
        preferredObjectStoreId: {
            type: String,
            default: null,
        },
    },
    data() {
        return {
            popoverPlacement: "left",
            newDatasetsDescription: "New dataset outputs from tools and workflows",
            titleTag: "h3",
            modalSize: "sm",
            showModal: false,
            selectedObjectStoreId: this.preferredObjectStoreId,
        };
    },
    methods: {
        resetModal() {},
        async handleSubmit(preferredObjectStoreId) {
            const payload = { preferred_object_store_id: preferredObjectStoreId };
            try {
                await axios.put(`${this.root}api/users/current`, payload);
            } catch (e) {
                this.handleError(e);
            }
            this.selectedObjectStoreId = preferredObjectStoreId;
            this.showModal = false;
        },
    },
};
</script>

<style scoped>
@import "user-styles.scss";
</style>
