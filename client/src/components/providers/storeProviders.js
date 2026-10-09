// Simple dataset provider, looks at api for result, renders to slot prop
import axios from "axios";
import { mapActions, mapState } from "pinia";

import { useDbKeyStore } from "@/stores/dbKeyStore";
import { prependPath } from "@/utils/redirect";

import { useDatatypeStore } from "../../stores/datatypeStore";

function renderDefaultSlot(vm, slotProps) {
    // Use $scopedSlots for Vue 3 compat mode
    const slotFn = vm.$scopedSlots?.default || vm.$slots?.default;
    return slotFn ? slotFn(slotProps) : null;
}

export const SimpleProviderMixin = {
    // Renders the slot as a fragment, so there is no root element to put attributes on.
    inheritAttrs: false,
    props: {
        id: { type: String, required: true },
    },
    data() {
        return {
            loading: false,
            item: null,
            error: null,
        };
    },
    watch: {
        id: {
            immediate: true,
            handler(newVal, oldVal) {
                if (newVal !== oldVal) {
                    this.load();
                }
            },
        },
    },
    methods: {
        async load() {
            this.loading = true;
            const { data } = await axios.get(this.url);
            this.item = data;
            this.loading = false;
        },
        async save(newProps) {
            this.loading = true;
            const { data } = await axios.put(this.url, newProps);
            this.item = data;
            this.loading = false;
        },
    },
    render() {
        return renderDefaultSlot(this, {
            loading: this.loading,
            item: this.item,
            error: this.error,
            save: this.save,
            result: this.item,
        });
    },
};

/**
 * Provider over an upload list a store loads once (`fetch` action) and whose loading and
 * error state it owns. Renders the slot with `item` (the list), `loading` and `error`.
 */
function uploadListProvider(useStore, { fetch, items, loading, error }) {
    return {
        inheritAttrs: false,
        computed: {
            ...mapState(useStore, { storeItems: items, storeLoading: loading, storeError: error }),
        },
        methods: {
            ...mapActions(useStore, { fetchItems: fetch }),
        },
        created() {
            // Failures surface through the store's error state.
            this.fetchItems().catch(() => {});
        },
        render() {
            return renderDefaultSlot(this, {
                loading: this.storeLoading,
                item: this.storeItems,
                result: this.storeItems,
                error: this.storeError,
            });
        },
    };
}

export const DbKeyProvider = uploadListProvider(useDbKeyStore, {
    fetch: "fetchUploadDbKeys",
    items: "getUploadDbKeys",
    loading: "uploadDbKeysLoading",
    error: "uploadDbKeysError",
});

export const DatatypesProvider = uploadListProvider(useDatatypeStore, {
    fetch: "fetchUploadDatatypes",
    items: "getUploadDatatypes",
    loading: "uploadDatatypesLoading",
    error: "uploadDatatypesError",
});

export const SuitableConvertersProvider = {
    mixins: [SimpleProviderMixin],
    computed: {
        url() {
            return prependPath(`/api/dataset_collections/${this.id}/suitable_converters`);
        },
    },
};

export const DatasetCollectionContentProvider = {
    mixins: [SimpleProviderMixin],
    computed: {
        url() {
            // ugh ...
            return prependPath(this.id);
        },
    },
};

export const JobProvider = {
    mixins: [SimpleProviderMixin],
    computed: {
        url() {
            return prependPath(`api/jobs/${this.id}?full=true`);
        },
    },
};

export const DatasetCollectionElementProvider = {
    mixins: [SimpleProviderMixin],
    computed: {
        url() {
            return prependPath(`api/dataset_collection_element/${this.id}`);
        },
    },
};
