<template>
    <span>
        <div v-for="(creator, index) in creators" :key="index">
            <CreatorViewer :creator="creator" />
        </div>
    </span>
</template>

<script>
import CreatorViewer from "./CreatorViewer";

export default {
    components: {
        CreatorViewer,
    },
    props: {
        creators: {
            type: Array,
        },
    },
};
</script>
