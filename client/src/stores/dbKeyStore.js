import { defineStore } from "pinia";

import { DEFAULT_DBKEY, getUploadDbKeys } from "@/components/Upload/utils";

export const useDbKeyStore = defineStore("dbKeyStore", {
    state: () => ({
        uploadDbKeys: [],
    }),
    getters: {
        getUploadDbKeys: (state) => {
            return state.uploadDbKeys;
        },
    },
    actions: {
        async fetchUploadDbKeys() {
            const data = await getUploadDbKeys(DEFAULT_DBKEY);
            this.uploadDbKeys = data;
        },
    },
});
