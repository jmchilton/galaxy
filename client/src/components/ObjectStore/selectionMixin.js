import axios from "axios";
import LoadingSpan from "components/LoadingSpan";
import DescribeObjectStore from "components/ObjectStore/DescribeObjectStore";
import { errorMessageAsString } from "utils/simple-error";
import ObjectStoreBadges from "components/ObjectStore/ObjectStoreBadges";
import ProvidedQuotaSourceUsageBar from "components/User/DiskUsage/Quota/ProvidedQuotaSourceUsageBar";

export default {
    components: {
        LoadingSpan,
        DescribeObjectStore,
        ObjectStoreBadges,
        ProvidedQuotaSourceUsageBar,
    },
    props: {
        root: {
            type: String,
            required: true,
        },
    },
    data() {
        return {
            loading: true,
            error: null,
            objectStores: [],
            loadingObjectStoreInfoMessage: "Loading object store information",
            galaxySelectionDefalutTitle: "Use Galaxy Defaults",
            galaxySelectionDefalutDescription:
                "Selecting this will reset Galaxy to default behaviors configured by your Galaxy administrator.",
            whyIsSelectionPreferredText: `
Selecting this will reset Galaxy to default behaviors configured by your Galaxy administrator.
Select a preferred object store for new datasets. This is should be thought of as a preferred
object store because depending the job and workflow configuration execution configuration of
this Galaxy instance - a different object store may be selected. After a dataset is created,
click on the info icon in the history panel to view information about where it is stored. If it
is not stored in the correct place, contact your Galaxy adminstrator for more information.
`,
        };
    },
    async mounted() {
        try {
            const { data } = await axios.get(`${this.root}api/object_store?selectable=true`);
            this.objectStores = data;
            this.loading = false;
        } catch (e) {
            this.handleError(e);
        }
    },
    methods: {
        handleError(e) {
            const errorMessage = errorMessageAsString(e);
            this.error = errorMessage;
        },
        variant(objectStoreId) {
            if (this.selectedObjectStoreId == objectStoreId) {
                return "outline-primary";
            } else {
                return "outline-info";
            }
        },
    },
};
