# Conditional Workflow Steps

A workflow step may carry a `when` expression. Galaxy evaluates it before the step runs;
if it evaluates false, the step is skipped and produces no outputs. This document covers
what the expression can read, the two ways to decide whether a step should run, and what
to do with the outputs of a step that might not run.

## What a `when` expression can read

The expression is a CWL-style `$(...)` body evaluated with an `inputs` object in scope.
`inputs` carries the step's tool state together with anything else connected to the step,
so an expression can read:

- **Tool parameters**, connected or not, in their tool-state shape. A parameter nested
  inside a `<conditional>` is addressed as `inputs.cond.param` or
  `inputs["cond"]["param"]`. Galaxy names the _connection_ with a flat, pipe-prefixed
  name (`cond|param`), but that spelling is not exposed to the expression.
- **Data inputs.** A connected dataset appears as an object with its metadata, so
  `$(inputs.reference.format != "bwa_mem2_index")` is a valid gate.
- **Extra connections** that are not tool parameters at all. Connecting an output to a
  name the tool does not define makes that value available to the expression and nothing
  else. This is how the `when` boolean convention works, and it generalizes.

## Gating on a boolean parameter

The common form, and the one the workflow editor writes when you pick _Run when a
boolean parameter is true_:

```yaml
steps:
  trim:
    tool_id: trimmomatic
    in:
      input: reads
      when: run_trimming
    when: $(inputs.when)
```

`run_trimming` is a boolean workflow input. `when` is not a Trimmomatic parameter — it is
an extra connection that exists only to be read by the expression.

## Gating on an input being provided

A workflow input declared `optional: true` may be connected to a _required_ tool data
parameter, as long as the step is gated on that input being present:

```yaml
inputs:
  mapped: data
  primer_scheme:
    type: data
    optional: true
steps:
  trim:
    tool_id: ivar_trim
    in:
      input_bam: mapped
      primer|input_bed: primer_scheme
    when: $(inputs.primer.input_bed !== null)
```

When the dataset is supplied the step runs normally. When it is omitted the gate
evaluates false and the step is skipped, so the tool never sees a missing required
parameter.

Without the gate this workflow fails: an omitted optional input is not implicitly
skipped, it reaches parameter validation as null and the job errors. The skip comes from
the expression and nothing else.

The workflow editor writes this expression for you. Choose _Run when an input is
provided_ on the step, or drop an optional output onto a required input and accept the
offer to gate the step.

## Gate, then merge

A gated step's outputs are optional, because the step might not run. Connecting one
straight into a required downstream input is refused, and correctly so — that downstream
step has no value to consume when the gate is false.

Merge with a fallback right after the gate instead of chaining gated steps:

```yaml
merge:
  type: pick_value
  in:
    input_0: trim/output_bam
    input_1: mapped
  state:
    mode: first_non_null
```

`pick_value` takes the first input that is not null, so the workflow continues with the
trimmed data when trimming ran and with the untrimmed data when it did not. Everything
downstream of `merge` sees an ordinary required dataset.

Two spellings exist. `type: pick_value` is the native workflow module described here; it
has an editor palette entry and a step form. Many published workflows instead use the
tool shed tool `iuc/pick_value`, which does the same job and reads the same way in a
workflow file. Prefer the module for new work.

## Running a tool in two different shapes

Tool state is fixed per step, so a tool that must run with a reference in one case and
without it in the other needs two steps with complementary gates. An extra connection
carries the dataset into both expressions, including the branch that does not consume it:

```yaml
with_ref:
  tool_id: some_tool
  in:
    ref: maybe_reference
    probe: maybe_reference
  when: $(inputs.probe !== null)
without_ref:
  tool_id: some_tool
  in:
    probe: maybe_reference
  when: $(inputs.probe === null)
merged:
  type: pick_value
  in:
    input_0: with_ref/out
    input_1: without_ref/out
  state:
    mode: first_non_null
```

Exactly one of the two runs, and `pick_value` picks up whichever did.

## Deleting a gating connection

An expression that reads a connection which no longer exists fails quietly: on a tool
parameter the state key survives as null, so the step is skipped on every run, and on an
extra connection the evaluation raises. The workflow editor's best-practices panel
reports it, so a gate left dangling by a deleted connection does not go unnoticed.
