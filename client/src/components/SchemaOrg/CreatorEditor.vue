<!--
TODO: 
- Allow organizations to be creators.
-->
<template>
    <div v-if="edit">
        <PersonForm :person="creator" @onSave="onSave" @onCancel="edit = false" />
    </div>
    <div v-else-if="creator">
        <div v-if="creator.class == 'Person'">
            <PersonViewer :person="creator">
                <template v-slot:buttons>
                    <font-awesome-icon v-b-tooltip.hover title="Edit Creator" icon="edit" @click="edit = true" />
                </template>
            </PersonViewer>
        </div>
    </div>
    <div v-else>
        <i><a href="#" @click.prevent="edit = true">Specify a creator.</a></i>
    </div>
</template>

<script>
import { FontAwesomeIcon } from "@fortawesome/vue-fontawesome";
import { library } from "@fortawesome/fontawesome-svg-core";
import { faEdit } from "@fortawesome/free-solid-svg-icons";

library.add(faEdit);

import PersonViewer from "./PersonViewer";
import PersonForm from "./PersonForm";

export default {
    components: {
        FontAwesomeIcon,
        PersonForm,
        PersonViewer,
    },
    props: {
        creator: {
            type: Object,
        },
    },
    data() {
        return {
            edit: false,
        };
    },
    methods: {
        onSave(person) {
            this.$emit("onCreator", person);
            this.edit = false;
        },
    },
};
</script>

<style></style>
