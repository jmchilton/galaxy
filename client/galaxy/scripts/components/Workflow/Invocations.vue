<template>
    <div>
        <h2 class="mb-3" v-if="showTitle">
            <span id="invocations-title">Workflow Invocations</span>
        </h2>
        <b-alert variant="info" show v-if="headerMessage && showTitle">
            {{ headerMessage }}
        </b-alert>
        <b-alert v-if="loading" variant="info" show>
            <loading-span message="Loading workflow invocation job data" />
        </b-alert>
        <div v-else>
            <b-alert v-if="!invocationItemsComputed.length" variant="secondary" show>
                {{ noInvocationsMessage }}
            </b-alert>
            <b-table
                v-else
                :fields="invocationFields"
                :items="invocationItemsComputed"
                v-model="invocationItemsModel"
                hover
                striped
                caption-top
                :busy="loading"
            >
                <template v-slot:table-caption>
                    <p v-if="showTitle">
                        These invocations are not finished scheduling - one or more steps are waiting on others steps to be
                        complete before the full structure of the jobs in the workflow can be determined.
                    </p>
                </template>
                <template v-slot:row-details="row">
                    <b-card>
                        <!-- set provideContext to false, since the table itself provides this information -->
                        <workflow-invocation-state :invocationId="row.item.id" :provideContext="false" />
                    </b-card>
                </template>
                <template v-slot:cell(details)="data">
                    <b-button
                        v-b-tooltip.hover.bottom
                        title="Show Invocation Details"
                        class="btn-sm fa fa-chevron-down"
                        v-if="!data.detailsShowing"
                        @click.stop="swapRowDetails(data)"
                    />
                    <b-button
                        v-b-tooltip.hover.bottom
                        title="Hide Invocation Details"
                        class="btn-sm fa fa-chevron-up"
                        v-if="data.detailsShowing"
                        @click.stop="swapRowDetails(data)"
                    />
                </template>
                <template v-slot:cell(workflow_id)="data">
                    <div v-if="!ownerGrid || !getWorkflowByInstanceId(data.item.workflow_id)">
                        {{ data.item.workflow_id }}
                    </div>
                    <div v-else>
                        <workflow-dropdown :workflow="getWorkflowByInstanceId(data.item.workflow_id)" />
                    </div>
                </template>
                <template v-slot:cell(history_id)="data">
                    <div v-if="!ownerGrid || !getHistoryById(data.item.history_id)">
                        {{ data.item.history_id }}
                    </div>
                    <div v-else>
                        <history-dropdown :history="getHistoryById(data.item.history_id)" />
                    </div>
                </template>
            </b-table>
        </div>
    </div>
</template>

<script>
import { getRootFromIndexLink } from "onload";
import { WorkflowInvocationState } from "components/WorkflowInvocationState";
import LoadingSpan from "components/LoadingSpan";
import WorkflowDropdown from "components/Workflow/WorkflowDropdown";
import HistoryDropdown from "components/History/HistoryDropdown";
import { mapCacheActions } from "vuex-cache";
import { mapGetters } from "vuex";

const DETAILS_FIELD = { key: "details", label: "" };
const WORKFLOW_FIELD = { key: "workflow_id", label: "Workflow" };
const HISTORY_FIELD = { key: "history_id", label: "History" };
const INVOCATION_ID_FIELD = { key: "id", label: "Invocation ID", complex: true };
const STATE_FIELD = { key: "state" };
const UPDATE_TIME_FIELD = { key: "update_time", label: "Last Update" };
const CREATE_TIME_FIELD = { key: "create_time", label: "Invocation Time", complex: true };
const FIELDS = [
    DETAILS_FIELD,
    WORKFLOW_FIELD,
    HISTORY_FIELD,
    INVOCATION_ID_FIELD,
    STATE_FIELD,
    UPDATE_TIME_FIELD,
    CREATE_TIME_FIELD,
];

export default {
    components: {
        WorkflowInvocationState,
        LoadingSpan,
        WorkflowDropdown,
        HistoryDropdown
    },
    props: {
        invocationItems: { type: Array, default: () => [] },
        loading: { type: Boolean, default: true },
        noInvocationsMessage: { type: String },
        headerMessage: { type: String, default: "" },
        showTitle: { type: Boolean, default: true },
        ownerGrid: { type: Boolean, default: true },
        simplified: { type: Boolean, default: false },
    },
    data() {
        const fields = FIELDS.filter(field => (!this.simplified || !field.complex) ? true : false);
        return {
            invocationItemsModel: [],
            invocationFields: fields,
            status: ""
        };
    },
    computed: {
        ...mapGetters(["getWorkflowByInstanceId", "getHistoryById"]),
        invocationItemsComputed() {
            return this.computeItems(this.invocationItems);
        }
    },
    methods: {
        ...mapCacheActions(["fetchWorkflowForInstanceId", "fetchHistoryForId"]),
        editLink(workflowId) {
            return getRootFromIndexLink() + "workflow/editor?id=" + this.getWorkflowByInstanceId(workflowId).id;
        },
        computeItems(items) {
            return items.map(invocation => {
                if (this.ownerGrid) {
                    this.fetchWorkflowForInstanceId(invocation["workflow_id"]);
                    this.fetchHistoryForId(invocation["history_id"]);
                }
                return {
                    id: invocation["id"],
                    create_time: invocation["create_time"],
                    update_time: invocation["update_time"],
                    workflow_id: invocation["workflow_id"],
                    history_id: invocation["history_id"],
                    state: invocation["state"],
                    _showDetails: false
                };
            });
        },
        swapRowDetails(row) {
            row.toggleDetails();
        },
        handleError(error) {
            console.error(error);
        }
    }
};
</script>
