<template>
    <span>
        <div v-for="(creator, index) in creators" :key="index">
            <OrganizationViewer v-if="creator.class == 'Organization'" :organization="creator" />
            <PersonViewer v-else :person="creator" />
        </div>
    </span>
</template>

<script>
import PersonViewer from "./PersonViewer";
import OrganizationViewer from "./OrganizationViewer";

export default {
    components: {
        OrganizationViewer,
        PersonViewer,
    },
    props: {
        creators: {
            type: Array,
        },
    },
};
</script>

<style></style>
