<!-- https://schema.org/Person -->
<template>
    <b-form @submit="onSave" @reset="onReset">
        <b-form-group label="Name" label-for="name">
            <b-form-input id="name" v-model="name" placeholder="Enter name."></b-form-input>
        </b-form-group>
        <b-form-group label="Email" label-for="email">
            <b-form-input id="email" v-model="email" placeholder="Enter email."></b-form-input>
        </b-form-group>
        <b-form-group label="Identifier" label-for="identifier">
            <!-- 
                Could verify this with the Public orcid search API, using more
                complicated APIs require an extra login token.
                api = orcid.PublicAPI(institution_key, institution_secret)
                api.search('orcid:0000-0002-6794-0756')
                {'result': [{'orcid-identifier': {'uri': 'http://orcid.org/0000-0002-6794-0756', 'path': '0000-0002-6794-0756', 'host': 'orcid.org'}}], 'num-found': 1}
            -->
            <b-form-input id="identifier" v-model="identifier" placeholder="Enter identifier."></b-form-input>
        </b-form-group>
        <b-button type="submit" variant="primary">Save</b-button>
        <b-button type="reset" variant="danger">Cancel</b-button>
    </b-form>
</template>

<script>
export default {
    props: {
        organization: {
            type: Object,
        },
    },
    data() {
        return {
            name: this.organization && this.organization.name,
            email: this.organization && this.organization.email,
            identifier: this.organization && this.organization.identifier,
        };
    },
    methods: {
        onSave(evt) {
            evt.preventDefault();
            const newOrganization = {};
            newOrganization.class = "Organization";
            newOrganization.email = this.email;
            newOrganization.name = this.name;
            newOrganization.identifier = this.identifier;
            console.log("newOrganization is ");
            console.log(newOrganization);
            this.$emit("onSave", newOrganization);
        },
        onReset(evt) {
            console.log("in onReset");
            evt.preventDefault();
            this.$emit("onReset");
        },
    },
};
</script>
