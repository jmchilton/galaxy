<template>
    <span itemprop="creator" itemscope itemtype="https://schema.org/Person">
        <font-awesome-icon ref="button" icon="user" />
        <b-popover
            triggers="click blur"
            :placement="hoverPlacement"
            :target="this.$refs['button'] || 'works-lazily'"
            title="Person"
        >
            <b-table striped :items="items"> </b-table>
        </b-popover>
        <span v-if="name">
            <meta itemprop="name" :content="person.name" v-if="person.name" />
            <meta itemprop="givenName" :content="person.givenName" v-if="person.givenName" />
            <meta itemprop="familyName" :content="person.familyName" v-if="person.familyName" />
            {{ name }}
            <span v-if="email">
                (<span itemprop="email" :content="person.email">{{ email }}</span
                >)
            </span>
        </span>
        <span itemprop="email" :content="person.email" v-else>
            {{ email }}
        </span>
        <a v-if="orcidLink" :href="orcidLink" target="_blank">
            <link itemprop="identifier" :href="orcidLink" />
            <font-awesome-icon v-b-tooltip.hover title="View orcid.org profile" :icon="['fab', 'orcid']" />
        </a>
        <a v-if="url" :href="url" target="_blank">
            <link itemprop="url" :href="url" />
            <font-awesome-icon v-b-tooltip.hover title="URL" icon="link" />
        </a>
        <meta
            v-for="attribute in explicitMetaAttributes"
            :key="attribute.attribute"
            :itemprop="attribute.attribute"
            :content="attribute.value"
        />
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
        hoverPlacement: {
            type: String,
            default: "left",
        },
    },
    computed: {
        explicitMetaAttributes() {
            return this.items.filter(
                (i) => ["name", "givenName", "email", "familyName", "url", "identifier"].indexOf(i.attribute) == -1
            );
        },
        items() {
            const items = [];
            for (const key in this.person) {
                if (key == "class") {
                    continue;
                }
                items.push({ attribute: key, value: this.person[key] });
            }
            return items;
        },
        name() {
            let name = this.person.name;
            const familyName = this.person.familyName;
            const givenName = this.person.givenName;
            if (name == null && (familyName || givenName)) {
                const honorificPrefix = this.person.honorificPrefix;
                const honorificSuffix = this.person.honorificSuffix;
                if (givenName && familyName) {
                    name = givenName + " " + familyName;
                } else if (givenName) {
                    name = givenName;
                } else {
                    name = familyName;
                }
                if (honorificPrefix) {
                    name = honorificPrefix + " " + name;
                }
                if (honorificSuffix) {
                    name = name + " " + honorificSuffix;
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
