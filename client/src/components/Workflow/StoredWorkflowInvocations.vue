<script setup lang="ts">
import { faColumns } from "@fortawesome/free-solid-svg-icons";
import { FontAwesomeIcon } from "@fortawesome/vue-fontawesome";
import { computed, onMounted, ref } from "vue";

import { GalaxyApi } from "@/api";
import type { StoredWorkflowDetailed } from "@/api/workflows";
import { comparisonPath } from "@/components/Comparison/comparisonQuery";
import { rethrowSimple } from "@/utils/simple-error";

import GridInvocation from "../Grid/GridInvocation.vue";
import LoadingSpan from "../LoadingSpan.vue";
import GAlert from "@/components/BaseComponents/GAlert.vue";
import GButton from "@/components/BaseComponents/GButton.vue";
import BreadcrumbHeading from "@/components/Common/BreadcrumbHeading.vue";

interface Props {
    storedWorkflowId: string;
}
const props = defineProps<Props>();

const loading = ref(true);
const workflow = ref<StoredWorkflowDetailed>();

const compareOutputsLink = computed(() => comparisonPath("output_runs", { workflow_id: props.storedWorkflowId }));
const breadcrumbItems = computed(() => [
    { title: "Workflows", to: "/workflows/list" },
    { title: workflow.value?.name ?? "" },
    { title: "Invocations" },
]);

onMounted(async () => {
    try {
        const { data, error } = await GalaxyApi().GET("/api/workflows/{workflow_id}", {
            params: { path: { workflow_id: props.storedWorkflowId } },
        });

        if (error) {
            rethrowSimple(error);
        }

        workflow.value = data;
    } finally {
        loading.value = false;
    }
});
</script>

<template>
    <div v-if="!loading && workflow">
        <BreadcrumbHeading :items="breadcrumbItems">
            <GButton
                class="stored-workflow-compare-outputs text-nowrap"
                color="blue"
                size="small"
                outline
                :to="compareOutputsLink"
                title="Compare the labelled inputs and outputs of these runs side by side">
                <FontAwesomeIcon :icon="faColumns" />
                Compare outputs
            </GButton>
        </BreadcrumbHeading>
        <GridInvocation
            hide-heading
            :filtered-for="{
                type: 'StoredWorkflow',
                id: workflow.id,
                name: workflow.name,
            }" />
    </div>
    <GAlert v-else-if="loading" variant="info" show>
        <LoadingSpan message="Loading invocations for workflow" />
    </GAlert>
    <GAlert v-else variant="danger" show>
        <p>Failed to load stored workflow with ID: {{ props.storedWorkflowId }}</p>
    </GAlert>
</template>
