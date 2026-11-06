<script setup lang="ts">
import { faExclamationTriangle } from "@fortawesome/free-solid-svg-icons";
import { FontAwesomeIcon } from "@fortawesome/vue-fontawesome";
import { BAlert, BFormGroup, BFormInput, BModal, type BvModalEvent } from "bootstrap-vue";
import { storeToRefs } from "pinia";
import { computed, ref } from "vue";

import { GalaxyApi, isRegisteredUser } from "@/api";
import { useUserStore } from "@/stores/userStore";
import { userLogoutClient } from "@/utils/logout";

/** Backend `err_code` of a refusal by this instance's configuration (`CONFIG_DOES_NOT_ALLOW`) */
const CONFIG_DOES_NOT_ALLOW = 403004;

const CONFIG_REFUSAL_MESSAGE =
    "User deletion must be configured on this instance in order to allow user self-deletion.  Please contact an administrator for assistance.";
const GENERIC_ERROR_MESSAGE = "An error occurred while deleting the user.";

const emit = defineEmits<{
    (e: "reset"): void;
}>();

const userStore = useUserStore();
const { currentUser } = storeToRefs(userStore);

const touched = ref(false);
const userInput = ref("");
const deleteError = ref("");
const deleting = ref(false);

const userId = computed(() => (isRegisteredUser(currentUser.value) && currentUser.value?.id) || "");
const userEmail = computed(() => isRegisteredUser(currentUser.value) && currentUser.value?.email);
const inputState = computed(() => (touched.value ? nameState.value : null));
const nameState = computed(() => userInput.value === userEmail.value);
const showDeleteError = computed(() => {
    return deleteError.value !== "";
});

function resetModal() {
    userInput.value = "";
    deleting.value = false;
    emit("reset");
}

async function handleSubmit(event: BvModalEvent) {
    // Keep the modal open so a failed deletion can show its error; success logs out.
    event.preventDefault();
    if (nameState.value) {
        deleting.value = true;
        const error = await requestDeletion();
        if (error) {
            deleteError.value = error;
            deleting.value = false;
        } else {
            userLogoutClient();
        }
    }
}

/** Ask the server to delete the current user; resolves to the message to show if it did not. */
async function requestDeletion(): Promise<string | undefined> {
    try {
        const { error } = await GalaxyApi().DELETE("/api/users/{user_id}", {
            params: {
                path: {
                    user_id: userId.value,
                },
            },
        });
        if (error) {
            return error.err_code === CONFIG_DOES_NOT_ALLOW ? CONFIG_REFUSAL_MESSAGE : GENERIC_ERROR_MESSAGE;
        }
        return undefined;
    } catch {
        return GENERIC_ERROR_MESSAGE;
    }
}
</script>

<template>
    <BModal
        id="modal-user-deletion"
        centered
        title="Account Deletion"
        title-tag="h2"
        visible
        static
        ok-variant="danger"
        ok-title="Delete Account Permanently"
        cancel-variant="outline-primary"
        :ok-disabled="!nameState || deleting"
        @hidden="resetModal"
        @ok="handleSubmit">
        <BAlert variant="danger" :show="showDeleteError">{{ deleteError }}</BAlert>
        <BAlert variant="warning" show>
            <b>
                <FontAwesomeIcon :icon="faExclamationTriangle" />
                This action cannot be undone. Your account will be PERMANENTLY deleted, along with the data contained in
                it.
            </b>
        </BAlert>

        <BFormGroup
            :state="inputState"
            label="Enter your email address to confirm deletion"
            invalid-feedback="Email does not match the current user email.">
            <BFormInput id="name-input" v-model="userInput" :state="inputState" required @blur="touched = true" />
        </BFormGroup>
    </BModal>
</template>
