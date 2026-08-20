# Gating a step on optional-input presence — experimental results

Fixtures: `lib/galaxy_test/workflow/exp_*.gxwf.yml` (+ `-tests.yml`).
Run: `pytest lib/galaxy_test/workflow/test_framework_workflows.py -k exp_ -m workflow`
Result: 12/12 pass, all recording observed behavior.

## Findings

1. **`when: $(inputs.<data_param> !== null)` works.** `exp_a_toplevel` gates `cat` on its own
   required `input1`, fed by an omitted optional workflow input. Step skips; `pick_value`
   falls back. No shim, no boolean, no extra node.

2. **The optional -> required connection is accepted by the server.** gxformat2 import and
   the runtime both handle it. The refusal is purely client-side (`terminals.ts:378`).
   No `pick_value` launder is needed on the input side.

3. **Both key spellings resolve for a conditional-nested param.** `exp_a_nested_dot`
   (`$(inputs.cond.input1 !== null)`) and `exp_a_nested_bracket`
   (`$(inputs["cond|input1"] !== null)`) both pass. `execution_state.inputs` supplies the
   nested form, `extra_step_state` the flat prefixed form; both land in `step_state`.

4. **No implicit skip — control.** `exp_nogate` removes only the `when`. Same topology,
   optional omitted: tool request state `validation_failed`, job errors
   `Parameter 'input1': specify a dataset of the required format`. This proves the skip in
   (1) is caused by the `when` expression and not by upstream null propagation.

5. **The launder alone is not just insufficient, it is unsafe.** `exp_launder_only` wires
   optional -> `pick_value(first_or_skip)` -> `cat.input1` with no gate. Omitted input does
   NOT fail: `set_skipped` writes `json.dumps(None)`, so `cat` concatenates the literal
   text `null` into the output. Silent wrong answer, worse than the error in (4).

6. **A non-tool-param data connection works as a pure `when` probe.** `exp_twin_probe`
   connects `maybe` to a step input named `probe` that is not a tool parameter, on BOTH
   copies of a twin dispatch, gating `$(inputs.probe !== null)` / `$(inputs.probe === null)`.
   Both directions pass. `modules.py:~3137` resolves unknown step-input names via
   `replacement_for_connection(..., is_data=True)` into `extra_step_state`. This is the same
   mechanism the `id: when` convention rides.

## Client-side implications

- `terminals.ts:378` is the only blocker for the direct form. Relaxing it when the step's
  `when` references the target input unblocks (1)-(3) with no server change.
- `workflowStepStore.ts:476 findStepExtraInputs` synthesizes probe ports as
  `input_type: "parameter", type: "boolean"` — hardcoded. A data probe (6) would render as
  a boolean port receiving a dataset. Needs the terminal type inferred from the connection.
- No native module produces a presence boolean; `module_types` has only data_input,
  data_collection_input, parameter_input, pause, pick_value, tool, subworkflow.
