<template>
    <li class="dataset-source">
        <i>{{ source.source_uri }}</i>
    </li>
</template>

<script>
export default {
    props: {
        source: {
            type: Object,
            required: true,
        },
    },
};
</script>
