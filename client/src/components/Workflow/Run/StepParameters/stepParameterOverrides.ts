import type { components } from "@/api/schema";

/** ``step_parameter_overrides`` of an invocation request, keyed by step index. */
export type StepParameterOverrides = NonNullable<
    components["schemas"]["InvokeWorkflowPayload"]["step_parameter_overrides"]
>;

/** Names, and repeat instance indexes, leading to a parameter in nested tool state. */
export type ParameterPath = (string | number)[];

/** A parameter's key in ``step_parameter_overrides``: its step indexes, then its path, joined by ``/``. */
export function parameterKey(segments: (string | number)[]): string {
    return segments.join("/");
}

export function isPlainObject(value: unknown): value is Record<string, unknown> {
    return typeof value === "object" && value !== null && !Array.isArray(value);
}

/**
 * Leaf values of ``step_parameter_overrides`` by key (``2/queries/1/column``).
 *
 * A list of objects is a repeat - its empty instances set nothing; any other list is a value.
 */
export function stepParameterOverrideValues(overrides: unknown): Map<string, unknown> {
    const values = new Map<string, unknown>();
    const visit = (value: unknown, segments: (string | number)[]) => {
        if (isPlainObject(value)) {
            Object.entries(value).forEach(([name, child]) => visit(child, [...segments, name]));
        } else if (Array.isArray(value) && value.length && value.every(isPlainObject)) {
            value.forEach((child, i) => visit(child, [...segments, i]));
        } else if (segments.length) {
            values.set(parameterKey(segments), value);
        }
    };
    if (isPlainObject(overrides)) {
        visit(overrides, []);
    }
    return values;
}

export interface StepParameterValue {
    stepPath: number[];
    paramPath: ParameterPath;
    value: unknown;
}

/** ``step_parameter_overrides`` setting each parameter to its value; repeats are padded with empty instances. */
export function buildStepParameterOverrides(entries: StepParameterValue[]): StepParameterOverrides {
    const overrides: Record<string, any> = {};
    for (const { stepPath, paramPath, value } of entries) {
        const segments: (string | number)[] = [...stepPath.map(String), ...paramPath];
        let container: any = overrides;
        segments.forEach((segment, i) => {
            if (i === segments.length - 1) {
                container[segment] = value;
                return;
            }
            const next = segments[i + 1];
            if (container[segment] === undefined) {
                container[segment] = typeof next === "number" ? [] : {};
            }
            container = container[segment];
            if (Array.isArray(container) && typeof next === "number") {
                while (container.length <= next) {
                    container.push({});
                }
            }
        });
    }
    return overrides as StepParameterOverrides;
}

/** Parse the URL-encoded JSON ``step_parameter_overrides`` route argument. */
export function parseStepParameterOverridesArg(arg: string | undefined | null): {
    overrides?: Record<string, unknown>;
    error?: string;
} {
    if (!arg) {
        return {};
    }
    try {
        const overrides = JSON.parse(arg);
        if (!isPlainObject(overrides)) {
            return { error: "step_parameter_overrides must be a JSON object keyed by step index" };
        }
        return { overrides };
    } catch (e) {
        return { error: `step_parameter_overrides is not valid JSON: ${e}` };
    }
}
