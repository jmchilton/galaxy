import { type components, GalaxyApi, type GalaxyApiPaths } from "@/api";
import { rethrowSimple } from "@/utils/simple-error";

export type ComparisonTable = components["schemas"]["ComparisonTable"];
export type ComparisonColumn = components["schemas"]["ComparisonColumn"];
export type ComparisonRow = components["schemas"]["ComparisonRow"];
export type ComparisonCell = ComparisonRow["cells"][string];
export type DatasetCell = components["schemas"]["DatasetCell"];
export type CollectionCell = components["schemas"]["CollectionCell"];
export type ValueCell = components["schemas"]["ValueCell"];
export type MissingCell = components["schemas"]["MissingCell"];
export type MissingReason = MissingCell["reason"];
export type ComparisonQuery = ComparisonTable["query"];
export type ComparisonKind = ComparisonQuery["kind"];

type QueryOf<P extends keyof GalaxyApiPaths> = GalaxyApiPaths[P] extends {
    get: { parameters: { query?: infer Q } };
}
    ? NonNullable<Q>
    : never;

export type StepRunsParams = QueryOf<"/api/workflows/{workflow_id}/step_runs"> & { workflow_id: string };
export type OutputRunsParams = QueryOf<"/api/workflows/{workflow_id}/output_runs"> & { workflow_id: string };
export type ToolRunsParams = QueryOf<"/api/tool_runs">;

export interface ComparisonResult {
    table: ComparisonTable;
    /** Rows matching the query before paging, from the `total_matches` header. */
    total: number;
}

function totalMatches(response: Response): number {
    return parseInt(response.headers.get("total_matches") ?? "0", 10) || 0;
}

export async function fetchStepRuns(params: StepRunsParams, signal?: AbortSignal): Promise<ComparisonResult> {
    const { workflow_id, ...query } = params;
    const { data, error, response } = await GalaxyApi().GET("/api/workflows/{workflow_id}/step_runs", {
        params: { path: { workflow_id }, query },
        signal,
    });
    if (error) {
        rethrowSimple(error);
    }
    return { table: data, total: totalMatches(response) };
}

export async function fetchOutputRuns(params: OutputRunsParams, signal?: AbortSignal): Promise<ComparisonResult> {
    const { workflow_id, ...query } = params;
    const { data, error, response } = await GalaxyApi().GET("/api/workflows/{workflow_id}/output_runs", {
        params: { path: { workflow_id }, query },
        signal,
    });
    if (error) {
        rethrowSimple(error);
    }
    return { table: data, total: totalMatches(response) };
}

export async function fetchToolRuns(params: ToolRunsParams, signal?: AbortSignal): Promise<ComparisonResult> {
    const { data, error, response } = await GalaxyApi().GET("/api/tool_runs", { params: { query: params }, signal });
    if (error) {
        rethrowSimple(error);
    }
    return { table: data, total: totalMatches(response) };
}

export type ComparisonRequest =
    | { kind: "step_runs"; params: StepRunsParams }
    | { kind: "output_runs"; params: OutputRunsParams }
    | { kind: "tool_runs"; params: ToolRunsParams };

/** Fetches whichever comparison `request.kind` names. */
export function fetchComparison(request: ComparisonRequest, signal?: AbortSignal): Promise<ComparisonResult> {
    switch (request.kind) {
        case "step_runs":
            return fetchStepRuns(request.params, signal);
        case "output_runs":
            return fetchOutputRuns(request.params, signal);
        default:
            return fetchToolRuns(request.params, signal);
    }
}
