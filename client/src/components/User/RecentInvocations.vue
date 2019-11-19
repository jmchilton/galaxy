<template>
    <invocations
        :invocation-items="invocationItems"
        :loading="loading"
        :showTitle="showTitle"
        :simplified="simplified"
        header-message="Your most recent workflow invocations are displayed on this page."
        no-invocations-message="There are no invocations to be shown."
    >
    </invocations>
</template>

<script>
import Invocations from "../Workflow/Invocations";
import { getRecentInvocations } from "./UserServices";

export default {
    components: {
        Invocations,
    },
    props: {
        showTitle: {
            type: Boolean,
            default: true,
        },
        simplified: {
            type: Boolean,
            default: false,
        },
    },
    data() {
        return {
            invocationItems: [],
            loading: true,
        };
    },
    created() {
        getRecentInvocations()
            .then((response) => {
                this.invocationItems = response.data;
                this.loading = false;
            })
            .catch(this.handleError);
    },
    methods: {
        handleError(error) {
            console.error(error);
        },
    },
};
</script>
