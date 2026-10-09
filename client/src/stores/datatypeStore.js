import { defineStore } from "pinia";

import { fetchDatatypeDetails } from "@/api/datatypes";
import { AUTO_EXTENSION, getUploadDatatypes } from "@/components/Upload/utils";
import { errorMessageAsString } from "@/utils/simple-error";

export const useDatatypeStore = defineStore("datatypeStore", {
    state: () => ({
        uploadDatatypes: [],
        uploadDatatypesLoaded: false,
        uploadDatatypesError: /** @type {string | null} */ (null),
        datatypeDetails: {},
    }),
    getters: {
        getUploadDatatypes: (state) => {
            return state.uploadDatatypes;
        },
        uploadDatatypesLoading: (state) => {
            return !state.uploadDatatypesLoaded && !state.uploadDatatypesError;
        },
        getDatatypeDetails: (state) => (extension) => {
            return state.datatypeDetails[extension];
        },
        isDatatypeAutoDownload: (state) => (extension) => {
            const details = state.datatypeDetails[extension];
            return details?.display_behavior === "download";
        },
        getPreferredVisualization: (state) => (extension) => {
            const details = state.datatypeDetails[extension];
            return details?.preferred_visualization?.visualization || null;
        },
    },
    actions: {
        /** Load upload datatypes once; a failure is kept in `uploadDatatypesError`, rethrown, and retried next call. */
        async fetchUploadDatatypes() {
            if (this.uploadDatatypesLoaded) {
                return;
            }
            this.uploadDatatypesError = null;
            try {
                const data = await getUploadDatatypes(false, AUTO_EXTENSION);
                if (!this.uploadDatatypesLoaded) {
                    this.uploadDatatypes = data;
                    this.uploadDatatypesLoaded = true;
                }
            } catch (err) {
                this.uploadDatatypesError = errorMessageAsString(err);
                throw err;
            }
        },
        async fetchDatatypeDetails(extension) {
            // Return cached details if available
            if (this.datatypeDetails[extension]) {
                return this.datatypeDetails[extension];
            }

            try {
                const details = await fetchDatatypeDetails(extension);
                this.datatypeDetails[extension] = details;
                return details;
            } catch (err) {
                console.error(`Error: unable to load datatype details for ${extension}`, err);
                return null;
            }
        },
    },
});
