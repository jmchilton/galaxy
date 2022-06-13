<template>
    <b-popover :target="`history-storage-${historyId}`" triggers="hover" placement="bottomleft">
        <template v-slot:title>Preferred Target Object Store</template>
        <p class="history-preferred-object-store-inherited" v-if="historyPreferredObjectStoreId">
            This target object store has been set at the history level.
        </p>
        <p class="history-preferred-object-store-not-inherited" v-else>
            This target object store has been inherited from your user preferences (set in User -> Preferences ->
            Preferred Object Store). If that option is updated, this history will target that new default.
        </p>
        <ObjectStoreDetailsProvider
            :id="preferredObjectStoreId"
            v-if="preferredObjectStoreId"
            v-slot="{ result: storageInfo, loading: isLoadingStorageInfo }">
            <b-spinner v-if="isLoadingStorageInfo" />
            <DescribeObjectStore
                v-else
                what="Galaxy will default to storing this history's datasets in "
                :storage-info="storageInfo">
            </DescribeObjectStore>
        </ObjectStoreDetailsProvider>
        <div>Change this preference object store target by clicking on the storage button in the history panel.</div>
    </b-popover>
</template>

<script>
import { ObjectStoreDetailsProvider } from "components/providers/ObjectStoreProvider";
import DescribeObjectStore from "components/ObjectStore/DescribeObjectStore";

export default {
    components: {
        DescribeObjectStore,
        ObjectStoreDetailsProvider,
    },
    props: {
        historyId: {
            type: String,
            required: true,
        },
        historyPreferredObjectStoreId: {
            type: String,
        },
        user: { type: Object, required: true },
    },
    computed: {
        preferredObjectStoreId() {
            let id = this.historyPreferredObjectStoreId;
            if (!id) {
                id = this.user.preferred_object_store_id;
            }
            return id;
        },
    },
};
</script>
