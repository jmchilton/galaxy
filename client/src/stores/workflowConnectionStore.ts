import { computed, del, ref, set } from "vue";

import { defineScopedStore } from "./scopedStore";
import {
    getConnectionId,
    updateStepToConnections,
    updateTerminalToConnection,
    updateTerminalToTerminal,
} from "./workflowConnectionUtils";
import type { Connection, ConnectionId, InputTerminal, InvalidConnections, OutputTerminal, TerminalToOutputTerminals } from "./workflowStoreTypes";

export type WorkflowConnectionStore = ReturnType<typeof useConnectionStore>;

export const useConnectionStore = defineScopedStore("workflowConnectionStore", (_workflowId) => {
    const connections = ref<Readonly<Connection>[]>([]);
    const invalidConnections = ref<InvalidConnections>({});
    const inputTerminalToOutputTerminals = ref<TerminalToOutputTerminals>({});
    const terminalToConnection = ref<{ [index: string]: Connection[] }>({});
    const stepToConnections = ref<{ [index: number]: Connection[] }>({});

    function $reset() {
        connections.value = [];
        invalidConnections.value = {};
        inputTerminalToOutputTerminals.value = {};
        terminalToConnection.value = {};
        stepToConnections.value = {};
    }

    const getOutputTerminalsForInputTerminal = computed(
        () => (terminalId: string) => inputTerminalToOutputTerminals.value[terminalId] || ([] as OutputTerminal[]),
    );

    const getConnectionsForTerminal = computed(
        () => (terminalId: string) => terminalToConnection.value[terminalId] || ([] as Connection[]),
    );

    const getConnectionsForStep = computed(
        () => (stepId: number) => stepToConnections.value[stepId] || ([] as Connection[]),
    );

    /**
     * Internal: Add connection without updating step store
     * Used by workflowGraphStore coordinator
     */
    function addConnectionInternal(connection: Connection) {
        Object.freeze(connection);
        connections.value.push(connection);

        terminalToConnection.value = updateTerminalToConnection(connections.value);
        inputTerminalToOutputTerminals.value = updateTerminalToTerminal(connections.value);
        stepToConnections.value = updateStepToConnections(connections.value);
    }

    /**
     * Internal: Get connections to remove for a given terminal
     * Returns array of connections that match the terminal
     */
    function getConnectionsToRemove(terminal: InputTerminal | OutputTerminal | ConnectionId): Connection[] {
        return connections.value.filter((connection) => {
            const id = getConnectionId(connection);

            if (typeof terminal === "string") {
                return id === terminal;
            } else if (terminal.connectorType === "input") {
                return connection.input.stepId == terminal.stepId && connection.input.name == terminal.name;
            } else {
                return connection.output.stepId == terminal.stepId && connection.output.name == terminal.name;
            }
        });
    }

    /**
     * Internal: Remove connection without updating step store
     * Used by workflowGraphStore coordinator
     */
    function removeConnectionInternal(connection: Connection) {
        const id = getConnectionId(connection);
        connections.value = connections.value.filter((c) => getConnectionId(c) !== id);
        del(invalidConnections.value, id);

        terminalToConnection.value = updateTerminalToConnection(connections.value);
        inputTerminalToOutputTerminals.value = updateTerminalToTerminal(connections.value);
        stepToConnections.value = updateStepToConnections(connections.value);
    }


    function markInvalidConnection(connectionId: string, reason: string) {
        set(invalidConnections.value, connectionId, reason);
    }

    function dropFromInvalidConnections(connectionId: string) {
        del(invalidConnections.value, connectionId);
    }

    return {
        connections,
        invalidConnections,
        inputTerminalToOutputTerminals,
        terminalToConnection,
        stepToConnections,
        $reset,
        getOutputTerminalsForInputTerminal,
        getConnectionsForTerminal,
        getConnectionsForStep,
        markInvalidConnection,
        dropFromInvalidConnections,
        // Internal methods for coordinator
        addConnectionInternal,
        removeConnectionInternal,
        getConnectionsToRemove,
    };
});
