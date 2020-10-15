<!--
- Support more schema.org fields (givenName, familyName, etc..).
- Support exporting raw JSON for this field in some way.
-->
<template>
    <span itemprop="creator" itemscope itemtype="https://schema.org/Organization">
        <span v-if="name">
            <span itemprop="name">{{ name }}</span>
            <span v-if="email">
                (<span itemprop="email">{{ email }}</span
                >)
            </span>
        </span>
        <span itemprop="email" v-else-if="email">
            {{ email }}
        </span>
        <a v-if="url" :href="url" target="_blank">
            <link itemprop="url" :href="url" />
            <font-awesome-icon v-b-tooltip.hover title="Organization URL" icon="link" />
        </a>
        <slot name="buttons"></slot>
    </span>
</template>

<script>
import { FontAwesomeIcon } from "@fortawesome/vue-fontawesome";
import { library } from "@fortawesome/fontawesome-svg-core";

import { faLink } from "@fortawesome/free-solid-svg-icons";

import Vue from "vue";
import BootstrapVue from "bootstrap-vue";

library.add(faLink);

export default {
    components: {
        FontAwesomeIcon,
    },
    props: {
        organization: {
            type: Object,
        },
    },
    computed: {
        email() {
            let email = this.organization.email;
            if (email && email.indexOf("mailto:") == 0) {
                email = email.slice("mailto:".length);
            }
            return email;
        },
        name() {
            return this.organization.name;
        },
        url() {
            return this.organization.url;
        },
    },
};
</script>

<style></style>
