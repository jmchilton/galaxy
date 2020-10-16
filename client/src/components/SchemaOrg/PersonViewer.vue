<!--
- Support more schema.org fields (givenName, familyName, etc..).
- Support exporting raw JSON for this field in some way.
-->
<template>
    <span itemprop="creator" itemscope itemtype="https://schema.org/Person">
        <font-awesome-icon icon="user" />
        <span v-if="name">
            <span itemprop="name">{{ name }}</span>
            <span v-if="email">
                (<span itemprop="email">{{ email }}</span
                >)
            </span>
        </span>
        <span itemprop="email" v-else>
            {{ email }}
        </span>
        <a v-if="orcidLink" :href="orcidLink" target="_blank">
            <link itemprop="identifier" :href="orcidLink" />
            <font-awesome-icon v-b-tooltip.hover title="View orcid.org profile" :icon="['fab', 'orcid']" />
        </a>
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
import { faUser } from "@fortawesome/free-solid-svg-icons";

import { faOrcid } from "@fortawesome/free-brands-svg-icons";

import Vue from "vue";
import BootstrapVue from "bootstrap-vue";

library.add(faOrcid, faUser);

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
            let name = this.person.name;
            let familyName = this.person.familyName;
            let givenName = this.person.givenName;
            if (name == null && (familyName || givenName)) {
                if (givenName && familyName) {
                    name = givenName + " " + familyName;
                } else if (givenName) {
                    name = givenName;
                } else {
                    name = familyName;
                }
            }
            return name;
        },
        email() {
            let email = this.person.email;
            if (email && email.indexOf("mailto:") == 0) {
                email = email.slice("mailto:".length);
            }
            return email;
        },
        url() {
            return this.person.url;
        },
        orcidLink() {
            const identifier = this.person.identifier;
            // Maybe interpret any XXXX-XXXX-XXXX-XXXX as orcid ID?
            if (identifier && identifier.indexOf("orcid.org/") >= 0) {
                return identifier;
            } else {
                return null;
            }
        },
    },
};
</script>

<style></style>
