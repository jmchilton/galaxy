<!--
- Support more schema.org fields (givenName, familyName, etc..).
- Support exporting raw JSON for this field in some way.
-->
<template>
    <span itemprop="creator" itemscope itemtype="https://schema.org/Person">
        <span v-if="name">
            <span itemprop="name">{{ name }}</span>
            <span v-if="email">
                (<span itemprop="email">{{ email }}</span
                >)
            </span>
        </span>
        <span v-else>
            {{ email }}
        </span>
        <a v-if="orcidLink" :href="orcidLink" target="_blank">
            <link itemprop="identifier" :href="orcidLink" />
            <font-awesome-icon v-b-tooltip.hover title="View orcid.org profile" :icon="['fab', 'orcid']" />
        </a>
        <slot name="buttons"></slot>
    </span>
</template>

<script>
import { FontAwesomeIcon } from "@fortawesome/vue-fontawesome";
import { library } from "@fortawesome/fontawesome-svg-core";

import { faOrcid } from "@fortawesome/free-brands-svg-icons";

import Vue from "vue";
import BootstrapVue from "bootstrap-vue";

library.add(faOrcid);

export default {
    components: {
        FontAwesomeIcon,
    },
    props: {
        person: {
            type: Object,
        },
    },
    computed: {
        name() {
            // allow building up from givenName, familyName...
            return this.person.name;
        },
        email() {
            let email = this.person.email;
            if (email && email.indexOf("mailto:") == 0) {
                email = email.slice("mailto:".length);
            }
            return email;
        },
        orcidLink() {
            const identifier = this.person.identifier;
            // TODO: also check http, maybe interpret any XXXX-XXXX-XXXX-XXXX as orcid ID.
            console.log(identifier);
            if (identifier && identifier.indexOf("https://orcid.org/") == 0) {
                return identifier;
            } else {
                return null;
            }
        },
    },
};
</script>

<style></style>
