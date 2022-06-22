<template>
    <b-popover target="tool-storage" triggers="hover" placement="bottomleft">
        <template v-slot:title>Preferred Target Object Store</template>
        <p v-if="toolPreferredObjectStoreId">
            This target object store has been set at the tool level, by default history or user preferences will be used
            and if those are not set Galaxy will pick an adminstrator configured default.
        </p>
        <ShowSelectedObjectStore
            v-if="toolPreferredObjectStoreId"
            :preferred-object-store-id="toolPreferredObjectStoreId"
            forWhat="Galaxy will default to storing this tool run's output in">
        </ShowSelectedObjectStore>
        <div v-else>
            No selection has been made for this tool execution. Defaults from history, user, or Galaxy will be used.
        </div>
        <div v-localize>
            Change this preference object store target by clicking on the storage button in the tool header.
        </div>
    </b-popover>
</template>

<script>
import ShowSelectedObjectStore from "components/ObjectStore/ShowSelectedObjectStore";

export default {
    components: {
        ShowSelectedObjectStore,
    },
    props: {
        toolPreferredObjectStoreId: {
            type: String,
            default: null,
        },
        user: { type: Object, required: true },
    },
    computed: {
        preferredObjectStoreId() {
            return this.toolPreferredObjectStoreId;
        },
    },
};
</script>
