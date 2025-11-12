import { useConnectionStore } from "@/stores/workflowConnectionStore";
import { getConnectionId } from "@/stores/workflowConnectionUtils";
import type { NewStep, Step } from "@/stores/workflowStepStore";
import { useWorkflowStepStore } from "@/stores/workflowStepStore";
import type { Connection, ConnectionId, InputTerminal, OutputTerminal } from "@/stores/workflowStoreTypes";

import { defineScopedStore } from "./scopedStore";

/**
 * Workflow Graph Coordinator Store
 *
 * This store orchestrates operations across workflowConnectionStore and workflowStepStore
 * to maintain consistency between the two stores and avoid circular dependencies.
 *
 * ## Architecture
 *
 * The workflow editor manages a directed acyclic graph (DAG) with two complementary views:
 *
 * 1. **Step Store**: Manages individual workflow steps and their metadata
 * 2. **Connection Store**: Manages connections between steps
 *
 * These stores need to stay synchronized:
 * - When a connection is added/removed, both stores must be updated
 * - When a step is removed, all its connections must also be removed
 *
 * This store provides the high-level operations that ensure both stores stay in sync,
 * breaking the circular dependency between them.
 *
 * ## Usage
 *
 * ```typescript
 * // Instead of using step and connection stores separately:
 * const stepStore = useWorkflowStepStore(workflowId);
 * const connectionStore = useConnectionStore(workflowId);
 * connectionStore.addConnection(connection);
 * stepStore.addConnection(connection);
 *
 * // Use the graph store coordinator:
 * const graphStore = useWorkflowGraphStore(workflowId);
 * graphStore.addConnection(connection); // Handles both stores
 * ```
 */

export type WorkflowGraphStore = ReturnType<typeof useWorkflowGraphStore>;

export const useWorkflowGraphStore = defineScopedStore("workflowGraphStore", (workflowId) => {
    const stepStore = useWorkflowStepStore(workflowId);
    const connectionStore = useConnectionStore(workflowId);

    /**
     * Add a connection to both stores
     * @param connection The connection to add
     */
    function addConnection(connection: Connection) {
        // Add to connection store (internal method - no step store call)
        connectionStore.addConnectionInternal(connection);

        // Add to step store (internal method - no connection store call)
        stepStore.addConnectionInternal(connection);
    }

    /**
     * Remove connections from both stores
     * @param terminal Input/output terminal or connection ID to remove
     */
    function removeConnection(terminal: InputTerminal | OutputTerminal | ConnectionId) {
        // Get connections to remove from connection store
        const connectionsToRemove = connectionStore.getConnectionsToRemove(terminal);

        // Remove from both stores
        connectionsToRemove.forEach((connection) => {
            connectionStore.removeConnectionInternal(connection);
            stepStore.removeConnectionInternal(connection);
        });

        // Clean up invalid connections if it was a connection ID
        if (typeof terminal === "string") {
            connectionStore.dropFromInvalidConnections(terminal);
        }
    }

    /**
     * Add a step and optionally create its connections
     * @param newStep The step data to add
     * @param select Whether to select the step after adding
     * @param createConnections Whether to create connections from the step's input_connections
     * @returns The created step
     */
    function addStep(newStep: NewStep, select = false, createConnections = true): Step {
        // Add step (internal method - no connection store call)
        const step = stepStore.addStepInternal(newStep, select);

        // Create connections if needed
        if (createConnections) {
            // Import the helper function from workflowStepStore
            const connections = getConnectionsFromStep(step);
            connections.forEach((connection) => {
                addConnection(connection);
            });
        }

        return step;
    }

    /**
     * Remove a step and all its connections
     * @param stepId The ID of the step to remove
     */
    function removeStep(stepId: number) {
        // Get all connections for this step
        const connections = connectionStore.getConnectionsForStep(stepId);

        // Remove all connections (coordinated)
        connections.forEach((connection: Connection) => {
            removeConnection(getConnectionId(connection));
        });

        // Remove the step itself (internal method - no connection store call)
        stepStore.removeStepInternal(stepId);
    }

    /**
     * Helper to get connections from a step's input_connections property
     * This mirrors the stepToConnections function in workflowStepStore
     */
    function getConnectionsFromStep(step: Step): Connection[] {
        const connections: Connection[] = [];

        if (step.input_connections) {
            Object.entries(step.input_connections).forEach(([inputName, outputArray]) => {
                if (outputArray === undefined) {
                    return;
                }
                let outputs = outputArray;
                if (!Array.isArray(outputs)) {
                    outputs = [outputs];
                }
                outputs.forEach((output) => {
                    const connection: Connection = {
                        input: {
                            stepId: step.id,
                            name: inputName,
                            connectorType: "input",
                        },
                        output: {
                            stepId: output.id,
                            name: output.output_name,
                            connectorType: "output",
                        },
                    };
                    const connectionInput = step.inputs.find((input) => input.name == inputName);
                    if (connectionInput && "input_subworkflow_step_id" in connectionInput) {
                        connection.input.input_subworkflow_step_id = connectionInput.input_subworkflow_step_id;
                    }
                    connections.push(connection);
                });
            });
        }

        return connections;
    }

    return {
        // Coordinated operations
        addConnection,
        removeConnection,
        addStep,
        removeStep,

        // Direct access to step store state and methods
        steps: stepStore.steps,
        stepMapOver: stepStore.stepMapOver,
        stepInputMapOver: stepStore.stepInputMapOver,
        stepIndex: stepStore.stepIndex,
        stepExtraInputs: stepStore.stepExtraInputs,
        getStep: stepStore.getStep,
        getStepExtraInputs: stepStore.getStepExtraInputs,
        getStepIndex: stepStore.getStepIndex,
        hasActiveOutputs: stepStore.hasActiveOutputs,
        workflowOutputs: stepStore.workflowOutputs,
        duplicateLabels: stepStore.duplicateLabels,
        insertNewStep: stepStore.insertNewStep,
        updateStep: stepStore.updateStep,
        updateStepValue: stepStore.updateStepValue,
        changeStepMapOver: stepStore.changeStepMapOver,
        resetStepInputMapOver: stepStore.resetStepInputMapOver,
        changeStepInputMapOver: stepStore.changeStepInputMapOver,

        // Direct access to connection store state and methods
        connections: connectionStore.connections,
        invalidConnections: connectionStore.invalidConnections,
        inputTerminalToOutputTerminals: connectionStore.inputTerminalToOutputTerminals,
        terminalToConnection: connectionStore.terminalToConnection,
        stepToConnections: connectionStore.stepToConnections,
        getOutputTerminalsForInputTerminal: connectionStore.getOutputTerminalsForInputTerminal,
        getConnectionsForTerminal: connectionStore.getConnectionsForTerminal,
        getConnectionsForStep: connectionStore.getConnectionsForStep,
        markInvalidConnection: connectionStore.markInvalidConnection,
        dropFromInvalidConnections: connectionStore.dropFromInvalidConnections,

        // Reset method
        $reset: () => {
            stepStore.$reset();
            connectionStore.$reset();
        },
    };
});
