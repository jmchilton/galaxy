import { defineStore } from "pinia";

import { DEFAULT_DBKEY, getUploadDbKeys } from "@/components/Upload/utils";
import { errorMessageAsString } from "@/utils/simple-error";

export const useDbKeyStore = defineStore("dbKeyStore", {
    state: () => ({
        uploadDbKeys: [],
        uploadDbKeysLoaded: false,
        uploadDbKeysError: /** @type {string | null} */ (null),
    }),
    getters: {
        getUploadDbKeys: (state) => {
            return state.uploadDbKeys;
        },
        uploadDbKeysLoading: (state) => {
            return !state.uploadDbKeysLoaded && !state.uploadDbKeysError;
        },
    },
    actions: {
        /** Load upload dbkeys once; a failure is kept in `uploadDbKeysError`, rethrown, and retried next call. */
        async fetchUploadDbKeys() {
            if (this.uploadDbKeysLoaded) {
                return;
            }
            this.uploadDbKeysError = null;
            try {
                const data = await getUploadDbKeys(DEFAULT_DBKEY);
                if (!this.uploadDbKeysLoaded) {
                    this.uploadDbKeys = data;
                    this.uploadDbKeysLoaded = true;
                }
            } catch (err) {
                this.uploadDbKeysError = errorMessageAsString(err);
                throw err;
            }
        },
    },
});
