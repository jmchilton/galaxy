<template>
    <div>
        <loading-span v-if="loading" :message="loadingObjectStoreInfoMessage" />
        <div v-else>
            <b-alert v-if="error" variant="danger" show>
                {{ error }}
            </b-alert>
            <b-row>
                <b-col cols="7">
                    <b-button-group vertical size="lg" style="width: 100%">
                        <b-button
                            :variant="variant(null)"
                            id="no-preferred-object-store-button"
                            @click="handleSubmit(null)"
                            ><i>User Preference Defined Default</i></b-button
                        >
                        <b-button
                            :variant="variant(object_store.object_store_id)"
                            :id="`preferred-object-store-button-${object_store.object_store_id}`"
                            v-for="object_store in objectStores"
                            :key="object_store.object_store_id"
                            @click="handleSubmit(object_store.object_store_id)"
                            >{{ object_store.name }}
                            <ObjectStoreBadges :badges="object_store.badges" size="lg" :more-on-hover="false" />
                            <ProvidedQuotaSourceUsageBar :objectStore="object_store" :compact="true">
                            </ProvidedQuotaSourceUsageBar>
                        </b-button>
                    </b-button-group>
                </b-col>
                <b-col cols="5">
                    <p style="float: right" v-localize>
                        {{ whyIsSelectionPreferredText }}
                    </p>
                </b-col>
            </b-row>
            <b-popover
                target="no-preferred-object-store-button"
                triggers="hover"
                :placement="popoverPlacement"
                v-if="userPreferredObjectStoreId">
                <template v-slot:title
                    ><span v-localize>{{ userSelectionDefalutTitle }}</span></template
                >
                <span v-localize>{{ userSelectionDefalutDescription }}</span>
            </b-popover>
            <b-popover target="no-preferred-object-store-button" triggers="hover" :placement="popoverPlacement" v-else>
                <template v-slot:title
                    ><span v-localize>{{ galaxySelectionDefalutTitle }}</span></template
                >
                <span v-localize>{{ galaxySelectionDefalutTitle }}</span>
            </b-popover>
            <b-popover
                v-for="object_store in objectStores"
                :key="object_store.object_store_id"
                :target="`preferred-object-store-button-${object_store.object_store_id}`"
                triggers="hover"
                :placement="popoverPlacement">
                <template v-slot:title>{{ object_store.name }}</template>
                <DescribeObjectStore :what="newDatasetsDescription" :storage-info="object_store"> </DescribeObjectStore>
            </b-popover>
        </div>
    </div>
</template>

<script>
import axios from "axios";
import selectionMixin from "components/ObjectStore/selectionMixin";

export default {
    mixins: [selectionMixin],
    props: {
        userPreferredObjectStoreId: {
            type: String,
            required: true,
        },
        history: {
            type: Object,
            required: true,
        },
    },
    data() {
        const selectedObjectStoreId = this.history.preferred_object_store_id;
        return {
            selectedObjectStoreId: selectedObjectStoreId,
            newDatasetsDescription: "New dataset outputs from tools and workflows executed in this history",
            popoverPlacement: "left",
            userSelectionDefalutTitle: "Use Your User Preference Defaults",
            userSelectionDefalutDescription:
                "Selecting this will cause the history to not set a default and to fallback to your user preference defined default.",
        };
    },
    methods: {
        async handleSubmit(preferredObjectStoreId) {
            const payload = { preferred_object_store_id: preferredObjectStoreId };
            try {
                await axios.put(`${this.root}api/histories/${this.history.id}`, payload);
            } catch (e) {
                this.handleError(e);
            }
            this.selectedObjectStoreId = preferredObjectStoreId;
            this.$emit("updated", preferredObjectStoreId);
        },
    },
};
</script>
