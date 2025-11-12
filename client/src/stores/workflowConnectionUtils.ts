import { pushOrSet } from "@/utils/pushOrSet";

import type {
    BaseTerminal,
    Connection,
    ConnectionId,
    InputTerminal,
    OutputTerminal,
    TerminalToOutputTerminals,
} from "./workflowStoreTypes";

/**
 * Pure utility functions for workflow connections
 * These have no dependencies on stores, enabling them to be imported
 * by both workflowConnectionStore and workflowStepStore without
 * creating circular dependencies.
 */

export function getTerminalId(item: BaseTerminal): string {
    return `node-${item.stepId}-${item.connectorType}-${item.name}`;
}

export function getTerminals(item: Connection): { input: InputTerminal; output: OutputTerminal } {
    return {
        input: { stepId: item.input.stepId, name: item.input.name, connectorType: "input" },
        output: { stepId: item.output.stepId, name: item.output.name, connectorType: "output" },
    };
}

export function getConnectionId(item: Connection): ConnectionId {
    return `${item.input.stepId}-${item.input.name}-${item.output.stepId}-${item.output.name}`;
}

export function updateTerminalToTerminal(connections: Connection[]) {
    const inputTerminalToOutputTerminals: TerminalToOutputTerminals = {};
    connections.forEach((connection) => {
        const terminals = getTerminals(connection);
        const inputTerminalId = getTerminalId(terminals.input);
        pushOrSet(inputTerminalToOutputTerminals, inputTerminalId, terminals.output);
    });
    return inputTerminalToOutputTerminals;
}

export function updateTerminalToConnection(connections: Connection[]) {
    const terminalToConnection: { [index: string]: Connection[] } = {};
    connections.forEach((connection) => {
        const terminals = getTerminals(connection);
        const outputTerminalId = getTerminalId(terminals.output);
        pushOrSet(terminalToConnection, outputTerminalId, connection);
        const inputTerminalId = getTerminalId(terminals.input);
        pushOrSet(terminalToConnection, inputTerminalId, connection);
    });
    return terminalToConnection;
}

export function updateStepToConnections(connections: Connection[]) {
    const stepToConnections: { [index: number]: Connection[] } = {};
    connections.forEach((connection) => {
        pushOrSet(stepToConnections, connection.input.stepId, connection);
        pushOrSet(stepToConnections, connection.output.stepId, connection);
    });
    return stepToConnections;
}
