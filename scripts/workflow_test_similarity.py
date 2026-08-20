#!/usr/bin/env python
"""Fingerprint Galaxy's workflow test corpus and rank near-duplicate tests.

Test units are collected from three venues:

``workflow_framework``
    ``lib/galaxy_test/workflow/*.gxwf.yml`` paired with its ``*.gxwf-tests.yml``.
    One unit per test job, ids matching the pytest ids ``pytest_generate_tests``
    builds in ``test_framework_workflows.py``.
``workflow_api``
    ``class: GalaxyWorkflow`` documents embedded as string literals in
    ``lib/galaxy_test/api/test_workflows.py`` (including the shared literals in
    ``lib/galaxy_test/base/workflow_fixtures.py``). One unit per test method.
``tool_framework``
    ``<test>`` elements of the tools in ``test/functional/tools/``.

Each unit reduces to a fingerprint of tool ids, workflow constructs, input kinds
and assertion targets. Units are ranked against each other by Jaccard similarity
over the union of those four sets, so a proposed test can be measured against
what the corpus already covers instead of argued about.

Limitations worth knowing before quoting a number:

* Fingerprints describe the workflow document and the assertions, not the Python
  driving the run. Two API tests differing only in the run request - which inputs
  are supplied, which PJA is posted - can still score 1.00.
* ``BELONGS_AS_TOOL_TEST`` means the workflow contributes nothing to the
  behavior. When the subject is the invocation itself (job caching, invocation
  state, scheduling) that is still a wrong-venue signal, but the destination is
  an integration test rather than a tool test.
* ``mapped_over`` and ``multi_axis_mapping`` are graph heuristics. No tool schema
  is consulted, so a ``multiple="true"`` parameter consuming a collection is not
  distinguished from a map-over.

``--baseline REF`` splits the corpus: units the working tree adds relative to a
git ref are reported as candidates, each classified against its nearest existing
neighbours. Without it every unit is ranked against every other, which is how
pre-existing duplicates surface.
"""

import argparse
import ast
import json
import subprocess
import sys
import xml.etree.ElementTree as ET
from collections.abc import Iterable
from dataclasses import (
    dataclass,
    field,
)
from pathlib import Path
from typing import (
    Any,
)

import yaml

GALAXY_ROOT = Path(__file__).resolve().parent.parent
FRAMEWORK_WORKFLOW_DIR = Path("lib/galaxy_test/workflow")
API_TEST_FILE = Path("lib/galaxy_test/api/test_workflows.py")
API_FIXTURE_FILE = Path("lib/galaxy_test/base/workflow_fixtures.py")
TOOL_TEST_DIR = Path("test/functional/tools")

PJA_KEYS = {
    "hide",
    "rename",
    "delete_intermediate_datasets",
    "change_datatype",
    "set_columns",
    "add_tags",
    "remove_tags",
}

# The workflow-only construct set - mvdbeek's "most direct route" rule made
# mechanical. A test carrying none of these describes behavior a tool test can
# show, so its venue is wrong regardless of how novel the assertion is.
#
# Declared workflow outputs are tracked as a construct but deliberately left out
# of this set: every workflow declares outputs, so treating them as load-bearing
# would make the trigger vacuous. They are how a result is observed, not what is
# under test.
LOAD_BEARING_CONSTRUCTS = {
    "conditional_step",
    "skip_propagates",
    "subworkflow",
    "optional_input",
    "collection_operation",
    "pause",
    "replacement_parameters",
    "step_chain",
    "mapped_over",
    "multi_axis_mapping",
}

# Steps whose contract is consuming nulls - a pick_value module or any collection
# operation. A chain through one of these says nothing about whether a skip
# propagates to an ordinary tool step, which is what ``skip_propagates``
# isolates.
NULL_AWARE_STEPS = {"pick_value", "__PICK_VALUE__"}

# Assertion vocabularies differ per venue; normalize the ones that mean the same
# thing so Jaccard is not fooled by spelling.
ASSERTION_ALIASES = {
    "file_ext": "attr:ftype",
    "extension": "attr:ftype",
    "ftype": "attr:ftype",
    "visible": "attr:visible",
    "deleted": "attr:deleted",
    "misc_blurb": "attr:blurb",
    "blurb": "attr:blurb",
    "collection_type": "attr:collection_type",
    "element_identifier": "attr:element_identifier",
    "populated_state": "attr:populated_state",
    "state": "attr:state",
    "name": "attr:name",
    "dbkey": "attr:dbkey",
    "tags": "attr:tags",
    "metadata": "attr:metadata",
}

DUPLICATE_SIMILARITY = 0.8
SAME_SETUP_SIMILARITY = 0.6


@dataclass
class Fingerprint:
    id: str
    venue: str
    path: str
    tool_ids: set[str] = field(default_factory=set)
    constructs: set[str] = field(default_factory=set)
    input_kinds: set[str] = field(default_factory=set)
    assertion_targets: set[str] = field(default_factory=set)
    parameters: set[str] = field(default_factory=set)
    step_count: int = 0
    nesting_depth: int = 0
    job_count: int = 1
    doc: str = ""

    @property
    def features(self) -> set[str]:
        return (
            {f"tool:{t}" for t in self.tool_ids}
            | {f"construct:{c}" for c in self.constructs}
            | {f"input:{i}" for i in self.input_kinds}
            | {f"assert:{a}" for a in self.assertion_targets}
            | self.parameters
        )

    @property
    def setup_features(self) -> set[str]:
        """The shape of the workflow, without tool identity.

        Two tests that build the same structure are the same setup whether they
        drive ``cat`` or ``cat1``, and whether a ``pick_value`` runs in
        ``first_or_skip`` or ``the_only_non_null`` mode. Parameter values are
        deliberately absent: differing only in one is what PARAMETER_VARIANT
        means. The DUPLICATE trigger stays on the full feature set, where those
        values do count.
        """
        return {f"construct:{c}" for c in self.constructs} | {f"input:{i}" for i in self.input_kinds}

    @property
    def load_bearing(self) -> set[str]:
        return {c for c in self.constructs if c.split(":")[0] in LOAD_BEARING_CONSTRUCTS or c.startswith("pja:")}

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "venue": self.venue,
            "path": self.path,
            "tool_ids": sorted(self.tool_ids),
            "constructs": sorted(self.constructs),
            "input_kinds": sorted(self.input_kinds),
            "assertion_targets": sorted(self.assertion_targets),
            "parameters": sorted(self.parameters),
            "step_count": self.step_count,
            "nesting_depth": self.nesting_depth,
            "job_count": self.job_count,
        }


def jaccard(left: set[str], right: set[str]) -> float:
    if not left and not right:
        return 0.0
    return len(left & right) / len(left | right)


def _as_mapping(value: Any) -> dict[str, Any]:
    """gxformat2 accepts dicts keyed by label or lists of labelled dicts."""
    if isinstance(value, dict):
        return value
    if isinstance(value, list):
        out = {}
        for index, item in enumerate(value):
            if isinstance(item, dict):
                label = item.get("label") or item.get("id") or str(index)
                out[str(label)] = item
            else:
                out[str(index)] = item
        return out
    return {}


def _contains_replacement(value: Any) -> bool:
    if isinstance(value, str):
        return "${" in value
    if isinstance(value, dict):
        return any(_contains_replacement(v) for v in value.values())
    if isinstance(value, list):
        return any(_contains_replacement(v) for v in value)
    return False


def _input_kind(spec: Any) -> str:
    if isinstance(spec, str):
        return "collection" if spec == "data_collection" else spec
    if isinstance(spec, dict):
        kind = spec.get("type", "data")
        if kind == "data_collection":
            kind = "collection"
        if kind == "collection":
            collection_type = spec.get("collection_type")
            return f"collection:{collection_type}" if collection_type else "collection"
        return str(kind)
    return "data"


def analyze_workflow(workflow: dict[str, Any], fingerprint: Fingerprint, depth: int = 0) -> None:
    """Populate the construct/tool/input parts of a fingerprint from a gxformat2 dict."""
    fingerprint.nesting_depth = max(fingerprint.nesting_depth, depth)
    inputs = _as_mapping(workflow.get("inputs"))
    collection_inputs = set()
    for label, spec in inputs.items():
        kind = _input_kind(spec)
        fingerprint.input_kinds.add(kind)
        if kind.startswith("collection"):
            collection_inputs.add(label)
        if isinstance(spec, dict) and spec.get("optional"):
            fingerprint.constructs.add("optional_input")
            fingerprint.input_kinds.add(f"optional:{kind}")
    if workflow.get("outputs"):
        fingerprint.constructs.add("workflow_outputs")
    for label, value in _as_mapping(workflow.get("test_data")).items():
        # API literals carry their run request inline; without it two tests that
        # differ only in what they supply look identical.
        fingerprint.parameters.update(_flatten_state({label: value}))

    steps = _as_mapping(workflow.get("steps"))
    step_labels = set(steps.keys())
    conditional_labels = {
        label for label, step in steps.items() if isinstance(step, dict) and step.get("when") is not None
    }
    for _label, step in steps.items():
        if not isinstance(step, dict):
            continue
        fingerprint.step_count += 1
        tool_id = step.get("tool_id")
        step_type = step.get("type")
        if tool_id:
            fingerprint.tool_ids.add(str(tool_id))
            if str(tool_id).startswith("__"):
                fingerprint.constructs.add("collection_operation")
                fingerprint.constructs.add(f"module:{tool_id}")
        if step_type and step_type not in ("tool", "subworkflow"):
            fingerprint.constructs.add(f"module:{step_type}")
        if step_type == "pause" or tool_id == "pause":
            fingerprint.constructs.add("pause")
        if step.get("when") is not None:
            fingerprint.constructs.add("conditional_step")
            fingerprint.parameters.add(f"when:{str(step['when'])[:32]}")
        if "run" in step:
            # Some API tests assemble the child graph in Python and leave `run:
            # null` in the literal; the step is still a subworkflow step.
            fingerprint.constructs.add("subworkflow")
            if isinstance(step["run"], dict):
                analyze_workflow(step["run"], fingerprint, depth + 1)
        for _, out_spec in _as_mapping(step.get("outputs") or step.get("out")).items():
            if isinstance(out_spec, dict):
                for key in out_spec:
                    if key in PJA_KEYS:
                        fingerprint.constructs.add(f"pja:{key}")
        for key in ("state", "tool_state"):
            fingerprint.parameters.update(_flatten_state(step.get(key)))
        if _contains_replacement(step.get("outputs")) or _contains_replacement(step.get("state")):
            fingerprint.constructs.add("replacement_parameters")
        for source in _step_sources(step):
            head = source.split("/")[0]
            if head in step_labels:
                fingerprint.constructs.add("step_chain")
            if head in collection_inputs:
                fingerprint.constructs.add("mapped_over")

    mapped_axes = {
        source.split("/")[0]
        for step in steps.values()
        if isinstance(step, dict)
        for source in _step_sources(step)
        if source.split("/")[0] in collection_inputs
    }
    if len(mapped_axes) > 1:
        fingerprint.constructs.add("multi_axis_mapping")

    if _propagates_skip(steps, conditional_labels):
        fingerprint.constructs.add("skip_propagates")


def _flatten_state(state: Any, prefix: str = "") -> Iterable[str]:
    """Scalar leaves of a step's state as `key=value` features.

    Without these the fingerprint cannot tell a `first_or_skip` pick_value from a
    `the_only_non_null` one, and the whole family collapses to a single point.
    """
    if isinstance(state, dict):
        for key, value in state.items():
            if str(key).startswith("__"):
                continue
            yield from _flatten_state(value, f"{prefix}{key}.")
    elif isinstance(state, list):
        for item in state:
            yield from _flatten_state(item, prefix)
    elif state is not None and not isinstance(state, (dict, list)):
        yield f"state:{prefix.rstrip('.')}={str(state)[:24]}"


def _is_null_aware(step: dict[str, Any]) -> bool:
    tool_id = str(step.get("tool_id"))
    return step.get("type") in NULL_AWARE_STEPS or tool_id in NULL_AWARE_STEPS or tool_id.startswith("__")


def _propagates_skip(steps: dict[str, Any], conditional_labels: set[str]) -> bool:
    """True when an ordinary tool step is forced to skip by an upstream skip.

    A step only inherits a skip when *every* one of its sources is the output of
    a step that skips - a step that also reads a workflow input can still run, so
    it observes a null rather than propagating one. Null-aware steps
    (``pick_value``, collection operations) are excluded: consuming a null is
    their contract, not evidence that a skip travelled.
    """
    skipping = set(conditional_labels)
    changed = True
    propagating = False
    while changed:
        changed = False
        for label, step in steps.items():
            if not isinstance(step, dict) or label in skipping or _is_null_aware(step):
                continue
            sources = [source.split("/")[0] for source in _step_sources(step)]
            if sources and all(source in skipping for source in sources):
                skipping.add(label)
                propagating = True
                changed = True
    return propagating


def _step_sources(step: dict[str, Any]) -> Iterable[str]:
    for _, connection in _as_mapping(step.get("in")).items():
        if isinstance(connection, str):
            yield connection
        elif isinstance(connection, dict):
            source = connection.get("source")
            if isinstance(source, str):
                yield source
            elif isinstance(source, list):
                for item in source:
                    if isinstance(item, str):
                        yield item


def _normalize_assertion(target: str) -> str:
    return ASSERTION_ALIASES.get(target, target)


def analyze_test_outputs(outputs: Any, fingerprint: Fingerprint) -> None:
    if isinstance(outputs, dict):
        for _, spec in outputs.items():
            _analyze_output_spec(spec, fingerprint)


def _analyze_output_spec(spec: Any, fingerprint: Fingerprint) -> None:
    if not isinstance(spec, dict):
        fingerprint.assertion_targets.add("literal_value")
        return
    for key, value in spec.items():
        if key == "asserts":
            for assertion in value or []:
                if isinstance(assertion, dict) and assertion.get("that"):
                    fingerprint.assertion_targets.add(f"has:{assertion['that']}")
        elif key == "elements":
            fingerprint.assertion_targets.add("collection_elements")
            for _, element in _as_mapping(value).items():
                _analyze_output_spec(element, fingerprint)
        elif key in ("class", "name"):
            continue
        else:
            fingerprint.assertion_targets.add(_normalize_assertion(key))


def collect_framework_workflows(root: Path) -> list[Fingerprint]:
    """One fingerprint per fixture, unioning the assertions of all of its test jobs.

    Jobs of a fixture share a workflow, so fingerprinting them separately would
    rank every fixture against its own siblings. A fixture is also the unit a
    reviewer keeps or drops.
    """
    fingerprints = []
    directory = root / FRAMEWORK_WORKFLOW_DIR
    for workflow_path in sorted(directory.glob("*.gxwf.yml")):
        base_name = workflow_path.name[: -len(".gxwf.yml")]
        test_path = workflow_path.parent / f"{base_name}.gxwf-tests.yml"
        with workflow_path.open() as f:
            workflow = yaml.safe_load(f)
        jobs: list[Any] = []
        if test_path.exists():
            with test_path.open() as f:
                jobs = yaml.safe_load(f) or []
        fingerprint = Fingerprint(
            id=base_name,
            venue="workflow_framework",
            path=str(workflow_path.relative_to(root)),
            doc=(workflow.get("doc") or "").strip().splitlines()[0] if workflow.get("doc") else "",
        )
        fingerprint.job_count = len(jobs)
        analyze_workflow(workflow, fingerprint)
        for job in jobs:
            if not isinstance(job, dict):
                continue
            analyze_test_outputs(job.get("outputs"), fingerprint)
            if job.get("expect_failure"):
                fingerprint.assertion_targets.add("expect_failure")
            for _, value in (job.get("job") or {}).items():
                if isinstance(value, dict) and value.get("class"):
                    fingerprint.input_kinds.add(f"job:{value['class']}")
        fingerprints.append(fingerprint)
    return fingerprints


def _string_constants(module: ast.Module) -> dict[str, str]:
    constants = {}
    for node in module.body:
        if isinstance(node, ast.Assign) and isinstance(node.value, ast.Constant) and isinstance(node.value.value, str):
            for target in node.targets:
                if isinstance(target, ast.Name):
                    constants[target.id] = node.value.value
    return constants


def _assertion_targets_from_function(function: ast.AST) -> set[str]:
    """Dict keys and attribute names appearing inside `assert` statements."""
    targets: set[str] = set()
    for node in ast.walk(function):
        if not isinstance(node, ast.Assert):
            continue
        for inner in ast.walk(node):
            if isinstance(inner, ast.Subscript) and isinstance(inner.slice, ast.Constant):
                if isinstance(inner.slice.value, str):
                    targets.add(_normalize_assertion(inner.slice.value))
            elif isinstance(inner, ast.Attribute):
                targets.add(_normalize_assertion(inner.attr))
            elif isinstance(inner, ast.Call) and isinstance(inner.func, ast.Name):
                targets.add(f"call:{inner.func.id}")
    return targets


def collect_api_workflows(root: Path) -> tuple[list[Fingerprint], int]:
    api_path = root / API_TEST_FILE
    module = ast.parse(api_path.read_text())
    constants = _string_constants(module)
    fixtures_path = root / API_FIXTURE_FILE
    if fixtures_path.exists():
        constants.update(_string_constants(ast.parse(fixtures_path.read_text())))

    fingerprints: list[Fingerprint] = []
    unparsed = 0
    for class_node in ast.walk(module):
        if not isinstance(class_node, ast.ClassDef):
            continue
        for function in class_node.body:
            if not isinstance(function, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            if not function.name.startswith("test_"):
                continue
            documents = []
            for node in ast.walk(function):
                if isinstance(node, ast.Constant) and isinstance(node.value, str):
                    if "class: GalaxyWorkflow" in node.value:
                        documents.append(node.value)
                elif isinstance(node, ast.Name) and node.id in constants:
                    if "class: GalaxyWorkflow" in constants[node.id]:
                        documents.append(constants[node.id])
            if not documents:
                continue
            fingerprint = Fingerprint(
                id=f"{class_node.name}::{function.name}",
                venue="workflow_api",
                path=f"{API_TEST_FILE}:{function.lineno}",
            )
            for document in documents:
                try:
                    workflow = yaml.safe_load(document)
                except yaml.YAMLError:
                    unparsed += 1
                    continue
                if isinstance(workflow, dict):
                    analyze_workflow(workflow, fingerprint)
            fingerprint.assertion_targets |= _assertion_targets_from_function(function)
            fingerprints.append(fingerprint)
    return fingerprints, unparsed


def collect_tool_tests(root: Path) -> list[Fingerprint]:
    fingerprints = []
    for tool_path in sorted((root / TOOL_TEST_DIR).glob("*.xml")):
        try:
            tree = ET.parse(tool_path)
        except ET.ParseError:
            continue
        tool = tree.getroot()
        if tool.tag != "tool":
            continue
        tool_id = tool.get("id") or tool_path.stem
        param_types = {}
        for param in tool.iter("param"):
            if param.get("name"):
                param_types[param.get("name")] = param.get("type", "text")
        for index, test in enumerate(tool.iter("test")):
            fingerprint = Fingerprint(
                id=f"{tool_id}_{index}",
                venue="tool_framework",
                path=str(tool_path.relative_to(root)),
                tool_ids={tool_id},
                step_count=1,
            )
            for param in test.iter("param"):
                name = param.get("name")
                if name:
                    fingerprint.input_kinds.add(param_types.get(name, "text"))
            for element in test.iter():
                if element.tag in ("output", "output_collection", "element", "discovered_dataset"):
                    for attribute in element.keys():
                        if attribute != "name":
                            fingerprint.assertion_targets.add(_normalize_assertion(attribute))
                elif element.tag == "assert_contents":
                    for assertion in element:
                        fingerprint.assertion_targets.add(f"has:{assertion.tag}")
            fingerprints.append(fingerprint)
    return fingerprints


def collect_all(root: Path) -> tuple[list[Fingerprint], int]:
    api, unparsed = collect_api_workflows(root)
    return collect_framework_workflows(root) + api + collect_tool_tests(root), unparsed


def baseline_paths(root: Path, ref: str) -> set[str]:
    result = subprocess.run(
        ["git", "-C", str(root), "ls-tree", "-r", "--name-only", ref],
        capture_output=True,
        text=True,
        check=True,
    )
    return set(result.stdout.splitlines())


def baseline_api_test_ids(root: Path, ref: str) -> set[str]:
    """Test methods present in the ref's copy of the API test file.

    New methods added to a file that already exists would otherwise be counted
    as existing, which would let API-venue candidates escape classification.
    """
    result = subprocess.run(
        ["git", "-C", str(root), "show", f"{ref}:{API_TEST_FILE}"],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        return set()
    module = ast.parse(result.stdout)
    ids = set()
    for class_node in ast.walk(module):
        if isinstance(class_node, ast.ClassDef):
            for function in class_node.body:
                if isinstance(function, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    ids.add(f"{class_node.name}::{function.name}")
    return ids


def rank(candidate: Fingerprint, pool: list[Fingerprint], limit: int = 3) -> list[tuple[float, Fingerprint]]:
    scored = [(jaccard(candidate.features, other.features), other) for other in pool if other.id != candidate.id]
    scored.sort(key=lambda pair: (-pair[0], pair[1].id))
    return scored[:limit]


def tool_test_coverage(candidate: Fingerprint, pool: list[Fingerprint]) -> list[str]:
    """Tool tests already exercising any tool the candidate drives."""
    return sorted(other.id for other in pool if other.venue == "tool_framework" and other.tool_ids & candidate.tool_ids)


def _nearest(candidate: Fingerprint, pool: Iterable[Fingerprint]) -> tuple[float, Fingerprint] | None:
    scored = [(jaccard(candidate.features, other.features), other) for other in pool if other.id != candidate.id]
    if not scored:
        return None
    return max(scored, key=lambda pair: pair[0])


def classify(candidate: Fingerprint, existing: list[Fingerprint], candidates: list[Fingerprint]) -> tuple[str, str]:
    """Apply the closed verdict set, existing tests first.

    Precedence follows the disposition table: a wrong venue makes novelty moot, a
    duplicate of something already merged outranks a duplicate of something only
    proposed, and NOVEL_BEHAVIOR is reserved for a construct set nothing existing
    carries.
    """
    if not candidate.load_bearing:
        covered = tool_test_coverage(candidate, existing)
        tools = ", ".join(sorted(candidate.tool_ids)) or "its tools"
        detail = (
            f"no load-bearing workflow-only construct; {len(covered)} tool test(s) already drive {tools}"
            if covered
            else f"no load-bearing workflow-only construct, and {tools} has no tool test to extend"
        )
        return ("BELONGS_AS_TOOL_TEST", detail)

    nearest_existing = _nearest(candidate, existing)
    if nearest_existing:
        score, other = nearest_existing
        if score >= DUPLICATE_SIMILARITY and candidate.assertion_targets <= other.assertion_targets:
            return ("DUPLICATE", f"sim {score:.2f} vs `{other.id}`, asserts nothing that test does not")

    nearest_candidate = _nearest(candidate, candidates)
    if nearest_candidate:
        score, other = nearest_candidate
        if score >= DUPLICATE_SIMILARITY and candidate.assertion_targets <= other.assertion_targets:
            return (
                "DUPLICATE",
                f"sim {score:.2f} vs `{other.id}`, also proposed here and asserting everything this does",
            )

    for other in existing:
        if (
            other.venue.startswith("workflow")
            and other.constructs == candidate.constructs
            and other.tool_ids == candidate.tool_ids
            and (other.step_count != candidate.step_count or other.nesting_depth != candidate.nesting_depth)
        ):
            dimension = "nesting depth" if other.nesting_depth != candidate.nesting_depth else "step count"
            return (
                "PARAMETER_VARIANT",
                f"identical constructs and tools to `{other.id}`, differs only in {dimension} "
                f"(depth {other.nesting_depth}->{candidate.nesting_depth}, "
                f"steps {other.step_count}->{candidate.step_count})",
            )

    same_setup = [
        other
        for other in existing
        if other.venue.startswith("workflow") and candidate.load_bearing <= other.load_bearing
    ]
    if not same_setup:
        return ("NOVEL_BEHAVIOR", f"no existing test carries {', '.join(sorted(candidate.load_bearing))}")

    nearest_sharing = max(same_setup, key=lambda other: jaccard(candidate.setup_features, other.setup_features))
    sharing_score = jaccard(candidate.setup_features, nearest_sharing.setup_features)
    if sharing_score >= SAME_SETUP_SIMILARITY:
        new_targets = candidate.assertion_targets - nearest_sharing.assertion_targets
        return (
            "NOVEL_ASSERTION_ONLY",
            f"setup matches `{nearest_sharing.id}` (setup sim {sharing_score:.2f}); new assertions: "
            f"{', '.join(sorted(new_targets)) or 'none'}",
        )
    return (
        "NOVEL_BEHAVIOR",
        f"closest existing test sharing those constructs is `{nearest_sharing.id}` at setup sim {sharing_score:.2f}",
    )


def markdown_report(candidates: list[Fingerprint], existing: list[Fingerprint], limit: int) -> str:
    pool = existing + candidates
    candidate_ids = {candidate.id for candidate in candidates}
    lines = [
        "| Candidate | Load-bearing constructs | Nearest neighbours (Jaccard) | Verdict | Why |",
        "|---|---|---|---|---|",
    ]
    verdicts: dict[str, list[str]] = {}
    for candidate in sorted(candidates, key=lambda f: f.id):
        ranked = rank(candidate, pool, limit)
        verdict, why = classify(candidate, existing, candidates)
        verdicts.setdefault(verdict, []).append(candidate.id)
        neighbours = (
            "<br>".join(
                f"`{other.id}`{' *(also proposed)*' if other.id in candidate_ids else ''} {score:.2f}"
                for score, other in ranked
            )
            or "none"
        )
        constructs = ", ".join(sorted(candidate.load_bearing)) or "_none_"
        lines.append(f"| `{candidate.id}` | {constructs} | {neighbours} | **{verdict}** | {why} |")
    overlaps = [
        (left.id, right.id)
        for left in sorted(candidates, key=lambda f: f.id)
        for right in sorted(candidates, key=lambda f: f.id)
        if left.id < right.id and left.load_bearing and left.load_bearing == right.load_bearing
    ]
    if overlaps:
        lines.append("")
        lines.append("Candidates carrying an identical load-bearing construct set - only one of each pair")
        lines.append("can claim the behavior as novel:")
        lines.append("")
        for left, right in overlaps:
            lines.append(f"- `{left}` / `{right}`")
    lines.append("")
    lines.append("Verdict totals: " + ", ".join(f"{k} {len(v)}" for k, v in sorted(verdicts.items())))
    return "\n".join(lines)


def self_similarity_report(fingerprints: list[Fingerprint], threshold: float) -> str:
    lines = ["| Test A | Test B | Jaccard |", "|---|---|---|"]
    seen = set()
    pairs = []
    for left in fingerprints:
        for right in fingerprints:
            if left.id >= right.id:
                continue
            key = (left.id, right.id)
            if key in seen:
                continue
            seen.add(key)
            score = jaccard(left.features, right.features)
            if score >= threshold:
                pairs.append((score, left, right))
    pairs.sort(key=lambda triple: -triple[0])
    for score, left, right in pairs:
        lines.append(f"| `{left.id}` | `{right.id}` | {score:.2f} |")
    if not pairs:
        lines.append("| _none above threshold_ | | |")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--root", default=str(GALAXY_ROOT), help="Galaxy root to scan")
    parser.add_argument(
        "--baseline",
        action="append",
        default=[],
        help="git ref (repeatable); units whose defining file is absent from every ref are candidates",
    )
    parser.add_argument("--limit", type=int, default=3, help="neighbours to report per candidate")
    parser.add_argument(
        "--self-similarity",
        type=float,
        metavar="THRESHOLD",
        help="report pre-existing pairs in the corpus at or above THRESHOLD",
    )
    parser.add_argument("--json", action="store_true", help="dump fingerprints as JSON instead of markdown")
    args = parser.parse_args(argv)

    root = Path(args.root).resolve()
    fingerprints, unparsed = collect_all(root)

    if args.json:
        json.dump([f.to_dict() for f in fingerprints], sys.stdout, indent=2)
        sys.stdout.write("\n")
        return 0

    venues: dict[str, int] = {}
    for fingerprint in fingerprints:
        venues[fingerprint.venue] = venues.get(fingerprint.venue, 0) + 1
    print(f"Fingerprinted {len(fingerprints)} test units: " + ", ".join(f"{v} {k}" for k, v in sorted(venues.items())))
    if unparsed:
        print(f"({unparsed} embedded workflow literals did not parse as YAML and were skipped)")
    print()

    if args.self_similarity is not None:
        print(f"## Pre-existing pairs at or above {args.self_similarity}\n")
        print(self_similarity_report(fingerprints, args.self_similarity))
        print()

    if args.baseline:
        known: set[str] = set()
        known_api_tests: set[str] = set()
        for ref in args.baseline:
            known |= baseline_paths(root, ref)
            known_api_tests |= baseline_api_test_ids(root, ref)

        def _is_known(fingerprint: Fingerprint) -> bool:
            if fingerprint.venue == "workflow_api":
                return fingerprint.id in known_api_tests
            return fingerprint.path.split(":")[0] in known

        candidates = [f for f in fingerprints if not _is_known(f)]
        existing = [f for f in fingerprints if _is_known(f)]
        if not candidates:
            print(f"No test units introduced relative to {', '.join(args.baseline)}.")
            return 0
        print(f"## {len(candidates)} candidate units vs {len(existing)} existing\n")
        print(markdown_report(candidates, existing, args.limit))
    return 0


if __name__ == "__main__":
    sys.exit(main())
