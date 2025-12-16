# History Notebooks: Implementation Research

This document provides implementation context for a planning agent with Galaxy codebase access.

## Background Document

See `THE_PROBLEM_AND_GOAL.md` for motivation and vision.

## Key Insight: History Markdown as Fourth Context

Galaxy Markdown already supports three input contexts that converge to internal numeric IDs:

| Context | Example Reference | Resolves To |
|---------|-------------------|-------------|
| Workflow Markdown | `output="results"`, `step="bwa_mem"` | `history_dataset_id=12345` |
| Tool Output | output references | `history_dataset_id=12345` |
| Page API | `history_dataset_id=a1b2c3d4` (encoded) | `history_dataset_id=12345` |
| **History Markdown** | `hid=42` | `history_dataset_id=12345` |

History Markdown is the planned fourth context. The architecture is designed for this—see `images/markdown_contextual_addressing.plantuml.svg` in the architecture repo.

---

## Design Decisions (Resolved)

| Question | Decision |
|----------|----------|
| HID syntax | Use `hid=42` (simple form) |
| Opt-in vs automatic | Opt-in—explicit notebook creation |
| Revision granularity | Explicit "save version" for first pass |
| Permissions | Notebook permissions mirror history permissions exactly |
| Collections | Collections and datasets share an HID namespace—an HID may reference either |
| Deleted items | Frontend replaces component with message indicating content was deleted |

---

## Part 1: Database Models (Mirror Pages)

### How Pages Work

Pages use a revision-based model for version tracking:

```
Page (1) ←→ (N) PageRevision
```

Each save creates a new `PageRevision` record. This enables:
- Rollback to previous versions
- Version comparison
- Full edit history

### History Notebooks Should Mirror This

Create analogous models:

```
History (1) ←→ (0..1) HistoryNotebook ←→ (N) HistoryNotebookRevision
```

The `0..1` reflects opt-in creation—a history may have no notebook until explicitly created.

**Key Files to Examine:**
- `lib/galaxy/model/__init__.py` - Page/PageRevision models
- `lib/galaxy/model/mapping.py` - SQLAlchemy mappings
- `lib/galaxy/schema/schema.py` - Pydantic models for API
- `lib/galaxy/managers/pages.py` - Page business logic

---

## Part 2: History-Relative Addressing Syntax

### Current Directive Syntax

Block directive:
```markdown
```galaxy
history_dataset_as_table(history_dataset_id=12345, title="Results")
```
```

Inline directive:
```markdown
Text with ${galaxy history_dataset_name(output="results")} embedded.
```

### History-Relative Syntax

History notebooks reference items by HID:

```markdown
```galaxy
history_dataset_as_table(hid=42)
```
```

Since collections and datasets share the HID namespace, `hid=42` may resolve to either an HDA or HDCA. The directive determines valid types (dataset directives require HDA, collection directives require HDCA).

### Resolution Flow

```
History Notebook markdown     →  resolve_history_markdown()  →  Internal markdown
hid=42                        →  history_dataset_id=12345    →  rendered output
```

This parallels `resolve_invocation_markdown()` for workflow reports.

---

## Part 3: Backend Parsing Changes

### Key Files

**Pure parsing (no Galaxy deps):**
- `lib/galaxy/managers/markdown_parse.py`

**Galaxy integration:**
- `lib/galaxy/managers/markdown_util.py`

### What Needs Updating in markdown_parse.py

#### 1. ALLOWED_ARGUMENTS Dictionary

Add `hid` to dataset and collection directives:

```python
# Current pattern - each directive has allowed args
ALLOWED_ARGUMENTS = {
    "history_dataset_display": frozenset(["history_dataset_id", "title", ...]),
    "history_dataset_as_table": frozenset(["history_dataset_id", "title", ...]),
    # ... etc
}
```

Add new argument to relevant directives:
```python
"history_dataset_display": frozenset(["history_dataset_id", "hid", "title", ...]),
```

#### 2. Validation Logic

The validator should accept EITHER `history_dataset_id` OR `hid`, not require both. May need conditional validation:

```python
def _check_func_call(match, line_no):
    # Existing: validates args against ALLOWED_ARGUMENTS
    # New: also validate mutual exclusivity of id types
```

#### 3. Regex Patterns

Key patterns in markdown_parse.py:
- `GALAXY_FLAVORED_MARKDOWN_CONTAINER_LINE_PATTERN` - detects ` ```galaxy ` blocks
- `GALAXY_MARKDOWN_FUNCTION_CALL_LINE` - parses directive calls
- `ARG_VAL_REGEX` - parses argument values
- `UNENCODED_ID_PATTERN` / `ENCODED_ID_PATTERN` - ID conversions

New pattern needed for HID references:
```python
HID_PATTERN = r"(hid)=(\d+)"
```

---

## Part 4: Backend Resolution Changes (markdown_util.py)

### New Resolution Function

Create `resolve_history_markdown()` parallel to `resolve_invocation_markdown()`:

```python
def resolve_history_markdown(trans, history, markdown_content):
    """
    Resolve history-relative references (hid=N) to internal IDs.

    Args:
        trans: Galaxy transaction context
        history: The History object this notebook belongs to
        markdown_content: Raw markdown with hid references

    Returns:
        Markdown with hid=N resolved to history_dataset_id=N or
        history_dataset_collection_id=N depending on item type
    """
    # For each directive with hid=N:
    #   1. Look up item in history by hid (could be HDA or HDCA)
    #   2. Determine item type
    #   3. Replace hid=N with appropriate internal ID argument
```

### Integration Points

- Called when rendering history notebook for display
- Called before Page extraction (convert to page-compatible format)
- Called before workflow extraction (convert to workflow-compatible format)

### ID Encoding for Export

When extracting to Page, HIDs must convert to encoded IDs for URL safety:
```
hid=42 → history_dataset_id=12345 → history_dataset_id=a1b2c3d4 (encoded)
```

Use existing `ready_galaxy_markdown_for_export()` after resolution.

---

## Part 5: Workflow Extraction with Report

### The Key Transformation

When extracting workflow from history, history notebook references transform:

```
History Notebook:           Workflow Report:
hid=42                  →   output="mapping_results"
hid=38                  →   input="reference_genome"
```

### How This Works

1. User selects outputs to include in workflow
2. Galaxy traces computational graph backward
3. For each HID referenced in notebook:
   - Identify corresponding workflow step/output
   - Replace `hid=N` with `output="label"` or `step="label"`
4. Save transformed markdown as workflow report template

### Key Files

- `lib/galaxy/managers/workflows.py` - workflow extraction logic
- `lib/galaxy/workflow/extract.py` - history→workflow conversion
- Look for existing `extract_workflow` implementations

### Implementation Consideration

The notebook→report transformation needs:
- Mapping from history item → workflow output label
- Handling items that don't map (intermediate results, dead ends)
- Graceful degradation for references that can't resolve

---

## Part 6: Page Extraction

### Simpler Than Workflow

Extract notebook to Page:
1. Resolve all `hid=N` to `history_dataset_id=N` (or collection equivalent)
2. Encode IDs for Page API format
3. Create new Page with content
4. Optionally: create PageRevision from HistoryNotebookRevision history

### Permissions

The Page inherits objects from history—user must have access to referenced datasets. Since notebook permissions mirror history permissions exactly, this should be straightforward.

---

## Part 7: Frontend Changes

### API Endpoint

New endpoint to fetch history notebook:
```
GET /api/histories/{history_id}/notebook
GET /api/histories/{history_id}/notebook/revisions
PUT /api/histories/{history_id}/notebook
POST /api/histories/{history_id}/notebook  (create, opt-in)
```

### Component Integration

The existing Markdown rendering components should work with minimal changes:
- `client/src/components/Markdown/Markdown.vue` - main renderer
- `client/src/components/Markdown/MarkdownEditor.vue` - editor

May need new mode for "history notebook" similar to page/report modes.

### Deleted Item Handling

When a referenced HID no longer exists in history, the frontend should:
- Replace the directive component with an informative message
- Indicate the content has been deleted
- Preserve document structure (don't break rendering)

### Editor Context

MarkdownToolBox needs history-aware directive insertion:
- Show "Dataset 42" instead of requiring encoded ID
- Filter available objects to current history
- "Insert reference" workflow for history items

**Key Files:**
- `client/src/components/Markdown/MarkdownToolBox.vue`
- `client/src/components/Markdown/directives.yml`

---

## Part 8: Rich Embedding (Already Exists)

Galaxy Markdown already supports rich content beyond text/tables:

- **Vega-Lite** - Interactive data visualizations
- **Galaxy Visualization plugins** - Full viz framework
- **Vitessce** - Spatial single-cell viewers

These work via section type detection in frontend:
- `client/src/components/Markdown/parse.ts`
- `client/src/components/Markdown/Sections/`

History notebooks get these for free—no additional implementation needed.

---

## Summary: Implementation Phases

### Phase 1: Database Models
- Create HistoryNotebook and HistoryNotebookRevision models
- Mirror Page/PageRevision pattern
- Add API endpoints (opt-in creation)

### Phase 2: History-Relative Syntax
- Add `hid` to ALLOWED_ARGUMENTS in markdown_parse.py
- Create `resolve_history_markdown()` in markdown_util.py
- Handle both HDA and HDCA resolution
- Integrate with rendering pipeline

### Phase 3: Frontend Integration
- Add history notebook editor UI
- History-aware directive insertion
- Deleted item handling (show message)
- Preview and save workflow

### Phase 4: Extraction
- History notebook → Page (simpler)
- History notebook → Workflow report (complex, requires graph tracing)

### Phase 5: Agent Integration
- API for programmatic notebook updates
- Revision tracking for agent actions
- (This may come naturally from API design)

---

## Files to Examine (Galaxy Codebase)

**Models:**
- `lib/galaxy/model/__init__.py` - Page, PageRevision, History
- `lib/galaxy/model/mapping.py`

**Markdown:**
- `lib/galaxy/managers/markdown_parse.py` - pure parser
- `lib/galaxy/managers/markdown_util.py` - Galaxy integration

**Pages:**
- `lib/galaxy/managers/pages.py`
- `lib/galaxy/webapps/galaxy/api/pages.py`

**Workflows:**
- `lib/galaxy/workflow/extract.py`
- `lib/galaxy/managers/workflows.py`

**Frontend:**
- `client/src/components/Markdown/` - all markdown components
- `client/src/components/Markdown/MarkdownEditor.vue`
- `client/src/components/Markdown/directives.yml`
