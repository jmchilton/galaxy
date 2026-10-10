import { readdirSync, readFileSync } from "fs";
import { join, relative, resolve } from "path";
import { describe, expect, it } from "vitest";

import { findFixtureCalls, schemaOperations, staleFixtures, unusedFixtures } from "./checks";
import { apiFixture, apiFixtureFile, apiFixtureFiles } from "./index";

const CLIENT_DIR = resolve(__dirname, "../../..");
const FIXTURES_DIR = __dirname;
const SCANNED_DIRS = ["src", "tests"];
const SOURCE_FILE = /\.(ts|js|vue)$/;

const SCHEMA = `export interface paths {
    "/api/histories": {
        parameters: {
            query?: never;
        };
        /** List histories */
        get: operations["index_api_histories_get"];
        put?: never;
        post: operations["create_api_histories_post"];
    };
    "/api/histories/{history_id}": {
        get: operations["show_api_histories__history_id__get"];
        delete?: never;
    };
}
export interface components {
    "/api/not_a_path": {
        get: string;
    };
}`;

function sourceFiles(): string[] {
    return SCANNED_DIRS.flatMap((dir) =>
        readdirSync(join(CLIENT_DIR, dir), { recursive: true, encoding: "utf8" })
            .map((file) => join(CLIENT_DIR, dir, file))
            .filter((file) => SOURCE_FILE.test(file) && !file.startsWith(FIXTURES_DIR)),
    );
}

describe("apiFixture", () => {
    it("names a fixture file after the OpenAPI path and method", () => {
        expect(apiFixtureFile("/api/histories/{history_id}", "get", "view_detailed")).toBe(
            "api/histories/{history_id}/get.view_detailed.json",
        );
        expect(apiFixtureFile("/api/histories/{history_id}", "get", "missing", 404)).toBe(
            "api/histories/{history_id}/get.404.missing.json",
        );
    });

    it("explains how to capture a missing fixture", () => {
        expect(() => apiFixture("/api/histories", "get", "no_such_scenario")).toThrow(
            /No API fixture api\/histories\/get\.no_such_scenario\.json.*ClientFixtures\.capture/,
        );
    });
});

describe("schemaOperations", () => {
    it("lists the defined methods of each path", () => {
        expect([...schemaOperations(SCHEMA)]).toEqual([
            "/api/histories get",
            "/api/histories post",
            "/api/histories/{history_id} get",
        ]);
    });
});

describe("staleFixtures", () => {
    const operations = schemaOperations(SCHEMA);

    it("accepts fixtures for operations in the schema", () => {
        const files = ["api/histories/get.default.json", "api/histories/{history_id}/get.404.missing.json"];
        expect(staleFixtures(files, operations)).toEqual([]);
    });

    it("rejects renamed paths, undefined methods and malformed names", () => {
        const files = [
            "api/history/{history_id}/get.default.json",
            "api/histories/{history_id}/delete.default.json",
            "api/histories/get.View-Detailed.json",
            "api/histories/default.json",
        ];
        expect(staleFixtures(files, operations)).toEqual(files);
    });
});

describe("findFixtureCalls", () => {
    it("resolves literal calls, including ones prettier split across lines", () => {
        const source = `
            const history = apiFixture("/api/histories/{history_id}", "get", "view_detailed");
            const missing = apiFixture(
                "/api/histories/{history_id}",
                "get",
                "missing",
                404,
            );`;
        expect(findFixtureCalls(source)).toEqual({
            files: [
                "api/histories/{history_id}/get.view_detailed.json",
                "api/histories/{history_id}/get.404.missing.json",
            ],
            nonLiteral: [],
        });
    });

    it("flags calls with non-literal arguments", () => {
        const source = `apiFixture(path, "get", "default");\napiFixture<"get">("/api/histories", "get", "default");`;
        expect(findFixtureCalls(source).nonLiteral).toEqual([
            `apiFixture(path, "get", "default");`,
            `apiFixture<"get">("/api/histories", "get", "default");`,
        ]);
    });
});

describe("unusedFixtures", () => {
    it("lists files no call references", () => {
        const files = ["api/histories/get.default.json", "api/histories/get.archived.json"];
        expect(unusedFixtures(files, ["api/histories/get.default.json"])).toEqual(["api/histories/get.archived.json"]);
    });
});

describe("recorded API fixtures", () => {
    const calls = sourceFiles().map((file) => ({
        file: relative(CLIENT_DIR, file),
        ...findFixtureCalls(readFileSync(file, "utf8")),
    }));

    it("all name an operation in the OpenAPI schema", () => {
        const schema = readFileSync(join(CLIENT_DIR, "packages/api-client/src/schema/schema.ts"), "utf8");
        expect(staleFixtures(apiFixtureFiles(), schemaOperations(schema))).toEqual([]);
    });

    it("are each used by a test, story or factory", () => {
        expect(
            unusedFixtures(
                apiFixtureFiles(),
                calls.flatMap((call) => call.files),
            ),
        ).toEqual([]);
    });

    it("are loaded only with literal arguments", () => {
        const nonLiteral = calls.flatMap(({ file, nonLiteral }) => nonLiteral.map((call) => `${file}: ${call}`));
        expect(nonLiteral).toEqual([]);
    });

    it("are referenced only where they exist", () => {
        const present = new Set(apiFixtureFiles());
        const missing = calls.flatMap(({ file, files }) =>
            files.filter((fixture) => !present.has(fixture)).map((fixture) => `${file}: ${fixture}`),
        );
        expect(missing).toEqual([]);
    });
});
