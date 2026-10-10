/// <reference types="vite/client" />
/**
 * API responses recorded from a real Galaxy server, for tests and stories.
 *
 * Files are named `<OpenAPI path>/<method>[.<status>].<scenario>.json` and are
 * written by `ClientFixtures.capture` in `lib/galaxy_test/base/client_fixtures.py`.
 * Edit the capture, not the JSON: CI fails when a fixture drifts from the server.
 *
 * Arguments to `apiFixture` must be string literals so the unimported-fixture
 * check can find every use.
 */
import type { GalaxyApiPaths } from "@/api/schema";

type Method = "get" | "put" | "post" | "delete" | "patch";
type SuccessStatus = 200 | 201 | 202 | 203 | 204 | 206;

type Responses<P extends keyof GalaxyApiPaths, M extends Method> = GalaxyApiPaths[P][M] extends {
    responses: infer R;
}
    ? R
    : never;

type JsonBody<R> = R extends { content: { "application/json": infer B } } ? B : unknown;

/** OpenAPI paths that define `method`. */
export type ApiFixturePath<M extends Method> = {
    [P in keyof GalaxyApiPaths]: GalaxyApiPaths[P][M] extends { responses: unknown } ? P : never;
}[keyof GalaxyApiPaths];

type SuccessBody<P extends keyof GalaxyApiPaths, M extends Method> = JsonBody<
    Responses<P, M>[Extract<keyof Responses<P, M>, SuccessStatus>]
>;

type ErrorBody<P extends keyof GalaxyApiPaths, M extends Method, S extends number> = S extends keyof Responses<P, M>
    ? JsonBody<Responses<P, M>[S]>
    : JsonBody<Responses<P, M>[Extract<keyof Responses<P, M>, `${S extends 500 | 501 | 502 | 503 ? 5 : 4}XX`>]>;

const fixtures = import.meta.glob<unknown>("./api/**/*.json", { eager: true, import: "default" });

/** The fixture files present, as paths relative to this directory (`api/histories/get.default.json`). */
export function apiFixtureFiles(): string[] {
    return Object.keys(fixtures).map((key) => key.slice("./".length));
}

/** Relative file for a fixture, e.g. `api/histories/{history_id}/get.view_detailed.json`. */
export function apiFixtureFile(path: string, method: string, scenario: string, status?: number): string {
    const statusPart = status === undefined ? "" : `.${status}`;
    return `${path.replace(/^\//, "")}/${method}${statusPart}.${scenario}.json`;
}

/**
 * A copy of the response Galaxy returned for `method path`, typed from the OpenAPI schema.
 * Pass `status` only for error responses.
 */
export function apiFixture<M extends Method, P extends ApiFixturePath<M>>(
    path: P,
    method: M,
    scenario: string,
): SuccessBody<P, M>;
export function apiFixture<M extends Method, P extends ApiFixturePath<M>, S extends number>(
    path: P,
    method: M,
    scenario: string,
    status: S,
): ErrorBody<P, M, S>;
export function apiFixture(path: string, method: Method, scenario: string, status?: number): unknown {
    const file = apiFixtureFile(path, method, scenario, status);
    const key = `./${file}`;
    if (!(key in fixtures)) {
        throw new Error(
            `No API fixture ${file} in client/src/api/__fixtures__. Capture it with ClientFixtures.capture in lib/galaxy_test.`,
        );
    }
    return structuredClone(fixtures[key]);
}
