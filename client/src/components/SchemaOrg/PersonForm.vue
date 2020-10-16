<!-- https://schema.org/Person -->
<template>
    <b-form @submit="onSave" @reset="onReset">
        <div role="group" class="form-group" v-for="attribute in displayedAttributes" :key="attribute.key">
            <label :for="attribute.key">{{ attribute.label }}</label>
            <font-awesome-icon
                v-b-tooltip.hover
                title="Hide Attribute"
                icon="eye-slash"
                @click="onHide(attribute.key)"
            />
            <b-form-input
                :id="attribute.key"
                v-model="currentValues[attribute.key]"
                :placeholder="'Enter ' + attribute.placeholder + '.'"
                :type="attribute.type"
            >
            </b-form-input>
        </div>
        <div role="group" class="form-group">
            <b-form-select v-model="addAttribute" :options="addAttributes" size="sm"></b-form-select>
        </div>
        <b-button type="submit" variant="primary">Save</b-button>
        <b-button type="reset" variant="danger">Cancel</b-button>
    </b-form>
</template>

<script>
const ATTRIBUTES_INFO = [
    { key: "name", label: "Name", placeholder: "name" },
    { key: "givenName", label: "Given Name", placeholder: "given name" },
    { key: "familyName", label: "Family Name", placeholder: "family name" },
    { key: "url", label: "URL", placeholder: "URL", type: "URL", type: "url" },
    { key: "identifier", label: "Identifier (typically an orcid.org ID)", placeholder: "identifier" },
    { key: "image", label: "Image URL", placeholder: "image URL", type: "url" },
    { key: "address", label: "Address", placeholder: "address" },
    { key: "email", label: "Email", placeholder: "email", type: "email" },
    { key: "telephone", label: "Telephone", placeholder: "telephone", type: "tel" },
    { key: "faxNumber", label: "Fax Number", placeholder: "fax number", type: "tel" },
    { key: "alternateName", label: "Alternate Name", placeholder: "alternate name" },
    { key: "honorificPrefix", label: "Honorific Prefix (e.g. Dr/Mrs/Mr)", placeholder: "honorific prefix" },
    { key: "honorificSuffix", label: "Honorific Suffix (e.g. M.D.)", placeholder: "honorific suffix" },
    { key: "jobTitle", label: "Job Title", placeholder: "job title" },
];
const ATTRIBUTES = ATTRIBUTES_INFO.map((a) => a.key);

import { FontAwesomeIcon } from "@fortawesome/vue-fontawesome";
import { library } from "@fortawesome/fontawesome-svg-core";
import { faEyeSlash, faLink } from "@fortawesome/free-solid-svg-icons";

library.add(faEyeSlash, faLink);

export default {
    components: {
        FontAwesomeIcon,
    },
    props: {
        person: {
            type: Object,
        },
    },
    data() {
        const currentValues = {};
        const show = {};
        for (const attribute of ATTRIBUTES) {
            const showAttribute = attribute in this.person;
            if (showAttribute) {
                currentValues[attribute] = this.person[attribute];
            }
            show[attribute] = showAttribute;
        }
        return {
            show: show,
            currentValues: currentValues,
            addAttribute: null,
        };
    },
    computed: {
        addAttributes() {
            const options = [{ value: null, text: "Add attribute" }];
            for (const attribute of ATTRIBUTES_INFO) {
                if (!this.show[attribute.key]) {
                    options.push({ value: attribute.key, text: "- " + attribute.placeholder });
                }
            }
            return options;
        },
        displayedAttributes() {
            return ATTRIBUTES_INFO.filter((a) => this.show[a.key]);
        },
    },
    watch: {
        addAttribute() {
            if (this.addAttribute) {
                this.show[this.addAttribute] = true;
            }
            this.$nextTick(() => {
                this.addAttribute = null;
            });
        },
    },
    methods: {
        onSave(evt) {
            evt.preventDefault();
            const newPerson = {};
            newPerson.class = "Person";
            for (const attribute of ATTRIBUTES) {
                if (this.show[attribute]) {
                    newPerson[attribute] = this.currentValues[attribute];
                }
            }
            this.$emit("onSave", newPerson);
        },
        onReset(evt) {
            evt.preventDefault();
            this.$emit("onReset");
        },
        onHide(attributeKey) {
            this.show[attributeKey] = false;
        },
    },
};
</script>
