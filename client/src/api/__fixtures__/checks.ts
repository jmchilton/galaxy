/** Consistency checks between recorded API fixtures, the OpenAPI schema and the code using them. */
import { apiFixtureFile } from "./index";

const FIXTURE_FILE =
    /^(?<path>.+)\/(?<method>get|put|post|delete|patch)(?:\.(?<status>\d{3}))?\.(?<scenario>[a-z0-9]+(?:_[a-z0-9]+)*)\.json$/;
const SCHEMA_PATH = /^ {4}"(\/[^"]*)": \{$/;
const SCHEMA_METHOD = /^ {8}(get|put|post|delete|patch): /;
const CALL = /\bapiFixture\s*[(<]/g;
const LITERAL_CALL =
    /^apiFixture\(\s*(["'])(?<path>[^"']+)\1\s*,\s*(["'])(?<method>[^"']+)\3\s*,\s*(["'])(?<scenario>[^"']+)\5\s*(?:,\s*(?<status>\d{3})\s*)?,?\s*\)/;

/** `"<path> <method>"` for every operation in the generated `schema.ts`. */
export function schemaOperations(schemaSource: string): Set<string> {
    const operations = new Set<string>();
    const lines = schemaSource.split("\n");
    const start = lines.indexOf("export interface paths {");
    let path: string | undefined;
    for (const line of lines.slice(start + 1)) {
        if (line === "}") {
            break;
        }
        const pathMatch = SCHEMA_PATH.exec(line);
        if (pathMatch) {
            path = pathMatch[1];
            continue;
        }
        const methodMatch = SCHEMA_METHOD.exec(line);
        if (methodMatch && path) {
            operations.add(`${path} ${methodMatch[1]}`);
        }
    }
    return operations;
}

/** Fixture files that are misnamed or name an operation the schema doesn't have. */
export function staleFixtures(files: string[], operations: Set<string>): string[] {
    return files.filter((file) => {
        const groups = FIXTURE_FILE.exec(file)?.groups;
        return !groups || !operations.has(`/${groups.path} ${groups.method}`);
    });
}

export interface FixtureCalls {
    /** Fixture files the calls reference. */
    files: string[];
    /** Calls whose arguments aren't string literals. */
    nonLiteral: string[];
}

export function findFixtureCalls(source: string): FixtureCalls {
    const calls: FixtureCalls = { files: [], nonLiteral: [] };
    for (const match of source.matchAll(CALL)) {
        const rest = source.slice(match.index);
        const groups = LITERAL_CALL.exec(rest)?.groups;
        if (groups) {
            const status = groups.status === undefined ? undefined : Number(groups.status);
            calls.files.push(apiFixtureFile(groups.path!, groups.method!, groups.scenario!, status));
        } else {
            calls.nonLiteral.push(rest.split("\n")[0]!);
        }
    }
    return calls;
}

/** Fixture files no call references. */
export function unusedFixtures(files: string[], referenced: Iterable<string>): string[] {
    const used = new Set(referenced);
    return files.filter((file) => !used.has(file));
}
