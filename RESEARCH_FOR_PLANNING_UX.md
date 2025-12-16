# History Notebooks: Frontend/UX Implementation Research

This document complements `RESEARCH_FOR_PLANNING.md` (backend-focused) with frontend architecture and UX patterns.

## Background Documents

- `THE_PROBLEM_AND_GOAL.md` - Vision and motivation
- `RESEARCH_FOR_PLANNING.md` - Backend implementation research

---

## Design Decisions (Resolved)

| Question | Decision |
|----------|----------|
| Location - Iteration 1 | Full-page markdown viewer/editor in "main frame" |
| Location - Iteration 2 | Split view: markdown editor + agentic chat interface |
| Location - Later | Window manager integration for tool form coordination |
| HID insertion - Initial | Mirror Pages selection, isolate to current history, insert `hid=<>` |
| HID insertion - Later | Add drag-and-drop from history panel |
| Preview mode | Mirror Pages (toggle between preview and editor) |
| Agent edit tracking | `edit_source` field: 'user' (default) or 'agent' |
| Agent edit workflow | Agent saves as 'user' → offers amendment → on confirm saves as 'agent' |
| Revision management | Nice-to-have, not MVP, plan includes later phase |
| Extraction unmapped refs | Error blocks extraction (strict validation) |

---

## Part 1: Pages Editor/Preview Architecture

### Component Hierarchy

```
MarkdownEditor.vue (container)
├── Mode toggle: "text" | "editor" (cell-based)
├── TextEditor.vue (raw markdown with toolbar)
│   └── MarkdownToolBox.vue (directive insertion)
└── CellEditor.vue (visual block editor)
    └── CellWrapper.vue → CellCode.vue (ACE editor)

Markdown.vue (preview/render)
└── SectionWrapper.vue (routes by cell type)
    ├── MarkdownDefault.vue (standard markdown + KaTeX)
    ├── MarkdownGalaxy.vue (galaxy directives → 40+ components)
    ├── MarkdownVega.vue
    ├── MarkdownVisualization.vue
    └── MarkdownVitessce.vue
```

### Edit/Preview Mode Switching

Location: `MarkdownEditor.vue:10-18`

```vue
<b-form-radio-group v-model="editor" :options="editorOptions" />
<TextEditor v-if="editor === 'text'" ... />
<CellEditor v-else ... />
```

State is local Vue ref - no external store needed.

### Key Props

**MarkdownEditor:**
- `markdownText: string` - Raw markdown content
- `mode: "report" | "page"` - Controls available directives
- `labels?: WorkflowLabel[]` - For workflow reports
- `steps?: Record<string, any>` - Workflow step definitions

**Markdown (preview):**
- `markdownConfig: { content, markdown, title, id, ... }`
- `readOnly?: boolean`

### Parsing Pipeline

1. `parseMarkdown()` - Splits by ` ```[type] ` fences
2. `splitMarkdown()` - Parses galaxy directive blocks
3. `getArgs()` - Extracts function-style args: `name(arg1=val1, arg2=val2)`

### What History Notebooks Reuse

- **Directly reusable:** MarkdownEditor, Markdown, all Section renderers
- **Needs adaptation:** Mode prop (add "history_notebook"), MarkdownToolBox selection

**Key Files:**
- `client/src/components/Markdown/MarkdownEditor.vue`
- `client/src/components/Markdown/Markdown.vue`
- `client/src/components/Markdown/Editor/TextEditor.vue`
- `client/src/components/Markdown/parse.ts`
- `client/src/components/Markdown/Sections/MarkdownGalaxy.vue`

---

## Part 2: Pages Selection/Insertion Mechanism

### Current Flow

```
User clicks toolbox item
    ↓
MarkdownToolBox routes to handler (onHistoryDatasetId, onJobId, etc.)
    ↓
MarkdownDialog opens appropriate selector:
  - WORKFLOW CONTEXT → MarkdownSelector (choose label)
  - PAGE CONTEXT → DataDialog / BasicSelectionDialog
    ↓
User selects item → ID extracted
    ↓
Emit: `history_dataset_display(history_dataset_id=f2db41e1fa331b3e)`
    ↓
Parent inserts into editor
```

### Directive Metadata

`directives.yml` defines each directive:
```yaml
history_dataset_display:
  side_panel_name: Dataset
  help: Display a dataset and relevant options...
```

`directives.ts` maps to emitter handlers and builds toolbox entries.

### Changes for History Notebooks

1. **New mode:** Add `mode="history_notebook"` to MarkdownEditor
2. **Scoped selection:** DataDialog receives `history={currentHistoryId}` (already supported)
3. **HID output:** Change emit format:
   ```typescript
   // Current (Pages):
   emit("onInsert", `${directiveName}(history_dataset_id=${encodedId})`);

   // History Notebook:
   emit("onInsert", `${directiveName}(hid=${hid})`);
   ```
4. **Simpler flow:** No label selection needed (not workflow context)

### Implementation Approach

Create `MarkdownDialogHistory.vue` or add conditional logic:
```typescript
if (props.mode === "history_notebook") {
  // Use HID from selected item, not encoded ID
  emit("onInsert", `${directiveName}(hid=${item.hid})`);
} else {
  emit("onInsert", `${directiveName}(history_dataset_id=${item.id})`);
}
```

**Key Files:**
- `client/src/components/Markdown/MarkdownToolBox.vue`
- `client/src/components/Markdown/MarkdownDialog.vue`
- `client/src/components/Markdown/directives.yml`
- `client/src/components/DataDialog/DataDialog.vue`

---

## Part 3: Main Frame Integration

### Layout Architecture

```
App.vue
└── Analysis.vue (main authenticated layout)
    ├── ActivityBar (left - tool/activity icons)
    ├── #center (main content)
    │   ├── CenterFrame (iframe for legacy)
    │   └── router-view (modern Vue routes)
    └── FlexPanel (right - history panel)
        └── HistoryIndex
```

### Routing Pattern

Routes defined in `router.js`, nested under Analysis:
```javascript
{
  path: "/",
  component: Analysis,
  children: [
    { path: "datasets/:datasetId/:tab?", component: DatasetView, props: ... },
    { path: "visualizations/display", component: VisualizationDisplay, ... },
    // ... 100+ routes
  ]
}
```

### History Notebook Route

Add to `router.js`:
```javascript
{
  path: "histories/:historyId/notebook",
  component: HistoryNotebookView,
  props: (route) => ({
    historyId: route.params.historyId,
    displayOnly: route.query.displayOnly === "true"
  })
}
```

Navigation: `router.push(`/histories/${historyId}/notebook`)`

### Entry Points

1. **History panel action:** Add "Notebook" button/menu item to history header
2. **Direct URL:** `/histories/{id}/notebook`
3. **Activity bar:** Optional - add notebook activity icon

### Panel Visibility

Respects `?hide_panels=true` query param (for window manager):
```javascript
// usePanels.ts
showPanels = route.query.hide_panels !== "true"
```

**Key Files:**
- `client/src/entry/analysis/router.js`
- `client/src/entry/analysis/modules/Analysis.vue`
- `client/src/components/History/HistoryPanel.vue`

---

## Part 4: Window Manager Integration

### How It Works

`WindowManager` wraps WinBox library for floating windows:
```javascript
class WindowManager {
  add(options)  // Creates window with URL
  _build_url()  // Injects hide_panels=true, hide_masthead=true
}
```

### Router Interception

`router-push.js` patches Vue router:
```javascript
router.push(location, { title, preventWindowManager }) {
  if (title && !preventWindowManager && Galaxy.frame.active) {
    Galaxy.frame.add({ title, url: location });
    return;  // Don't update main route
  }
  // Normal routing
}
```

### Notebook Window Support

Components respect `displayOnly` prop to hide chrome when windowed:
```vue
<template>
  <div v-if="!displayOnly" class="notebook-toolbar">...</div>
  <div class="notebook-content">...</div>
</template>
```

Trigger from history panel:
```javascript
router.push(`/histories/${historyId}/notebook`, {
  title: `Notebook: ${historyName}`,
  preventWindowManager: false
});
```

### Implementation Note

Window manager integration is **later phase** - architecture should not preclude it, but MVP focuses on main frame view.

**Key Files:**
- `client/src/entry/analysis/window-manager.js`
- `client/src/entry/analysis/router-push.js`

---

## Part 5: Agentic Chat Interface (Iteration 2)

### Dependency

**Chat API is in separate branch** - this phase depends on that work being merged.

### No Existing Chat UI

Galaxy has no chat/conversation UI. Relevant patterns to build from:

| Pattern | Location | Useful For |
|---------|----------|------------|
| NotificationsList | `components/Notifications/` | Message list, filtering, batch ops |
| GCard | `components/Common/GCard.vue` | Message cards with timestamps, actions |
| ScrollList | `components/ScrollList/` | Infinite scroll, lazy loading |
| useResourceWatcher | `composables/resourceWatcher.ts` | Polling for updates |

### Proposed Architecture

```
HistoryNotebookSplit.vue
├── MarkdownEditor (left pane, 60%)
└── ChatPanel (right pane, 40%)
    ├── ChatHeader (history name, status)
    ├── ChatMessages (ScrollList of GCard-style messages)
    │   ├── UserMessage
    │   └── AgentMessage (with "Apply to notebook" action)
    ├── ChatInput (textarea + send button)
    └── PendingActions (agent amendments awaiting approval)
```

### Agent Amendment Workflow

1. Agent proposes change → shown in chat with diff preview
2. User clicks "Apply" → notebook updated, saved with `edit_source='agent'`
3. User clicks "Reject" → change discarded
4. Unsaved changes saved as `edit_source='user'` before agent edits

### Real-Time Updates

Options:
- **Polling:** useResourceWatcher pattern (30s active, 10m background)
- **WebSocket:** Better for chat, requires backend support

### Key Files to Reference

- `client/src/components/Notifications/NotificationsList.vue`
- `client/src/components/Notifications/NotificationCard.vue`
- `client/src/components/Common/GCard.vue`
- `client/src/stores/notificationsStore.ts`
- `client/src/composables/resourceWatcher.ts`

---

## Part 6: Revision Management (Nice-to-Have Phase)

### Current State

Pages have robust revision backend but **minimal revision UI**:
- API: `GET/POST /api/pages/{id}/revisions`
- Model: PageRevision with `create_time`, `update_time`, `content`
- Frontend: No revision browser, no diff viewer, no restore UI

This is a Galaxy-wide gap - notebooks could set the pattern.

### Proposed Revision UI

```
NotebookRevisionPanel.vue
├── RevisionList (Grid-based, sorted by create_time desc)
│   ├── Revision number
│   ├── Timestamp (relative + absolute)
│   ├── Author/source (user vs agent)
│   └── Actions: View, Compare, Restore
├── RevisionDiff (side-by-side or unified diff)
└── RestoreConfirmation modal
```

### Grid Pattern

Reuse existing Grid configs pattern:
```typescript
// configs/notebookRevisions.ts
fields: [
  { key: "revision", title: "Rev", type: "text" },
  { key: "create_time", title: "Date", type: "date" },
  { key: "edit_source", title: "Source", type: "text" },
  { key: "operations", title: "", type: "operations" }
]
```

### Integration Points

- Tab in notebook view: "Content" | "Revisions"
- Badge showing revision count
- "History" icon button in editor toolbar

**Key Files to Reference:**
- `client/src/components/Grid/configs/pages.ts`
- `client/src/components/Grid/configs/invocationsHistory.ts`
- `lib/galaxy/webapps/galaxy/api/page_revisions.py`

---

## Part 7: Drag-and-Drop (Later Phase)

### Target Behavior

Drag dataset from history panel → drop into markdown editor → inserts `hid=N` directive.

### Implementation Approach

1. **Draggable source:** History panel items already have drag support for reordering
2. **Drop target:** TextEditor textarea or CellEditor
3. **Data transfer:** Include `hid` in drag data
4. **Insert logic:** Determine directive type from drop context or show picker

### Existing Patterns

- History panel drag: `client/src/components/History/Content/`
- Workflow editor drag-drop: `client/src/components/Workflow/Editor/`

### Complexity

Medium - requires coordinating drag source (history panel) with drop target (editor) across component boundaries. Defer to later phase.

---

## Summary: Implementation Phases

### Phase 1: MVP (Full-Page Notebook View)

**Components:**
- `HistoryNotebookView.vue` - Main container
- `HistoryNotebookEditor.vue` - Wraps MarkdownEditor with history context
- Route: `/histories/:historyId/notebook`

**Changes to Existing:**
- `MarkdownEditor.vue` - Add `mode="history_notebook"`
- `MarkdownDialog.vue` - Emit `hid=N` instead of `history_dataset_id=N`
- `directives.ts` - Filter directives for history context
- `router.js` - Add notebook route

**Entry Point:**
- Button in history panel header: "Open Notebook"

### Phase 2: Agentic Chat (Split View)

**Dependency:** Chat API branch merged

**New Components:**
- `HistoryNotebookSplit.vue` - Split layout container
- `ChatPanel.vue` - Chat interface
- `ChatMessage.vue` - Message display
- `AgentAmendment.vue` - Approval UI for agent changes

**Backend:**
- `edit_source` field on HistoryNotebookRevision

### Phase 3: Window Manager

**Changes:**
- `HistoryNotebookView.vue` - Respect `displayOnly` prop
- History panel - Trigger windowed view via router with title

### Phase 4: Revision UI

**New Components:**
- `NotebookRevisionList.vue` - Grid-based revision browser
- `NotebookRevisionDiff.vue` - Diff viewer
- `configs/notebookRevisions.ts` - Grid config

### Phase 5: Drag-and-Drop

**Changes:**
- History panel items - Add notebook drop data
- TextEditor/CellEditor - Accept drops, insert directives

---

## Key Files Summary

### Must Modify

| File | Change |
|------|--------|
| `client/src/entry/analysis/router.js` | Add notebook route |
| `client/src/components/Markdown/MarkdownDialog.vue` | HID emission for history mode |
| `client/src/components/Markdown/directives.ts` | History notebook mode handling |
| `client/src/components/History/HistoryPanel.vue` | Add notebook entry point |

### Must Create

| File | Purpose |
|------|---------|
| `client/src/components/HistoryNotebook/HistoryNotebookView.vue` | Main view container |
| `client/src/components/HistoryNotebook/HistoryNotebookEditor.vue` | Editor wrapper |
| `client/src/stores/historyNotebookStore.ts` | Notebook state management |
| `client/src/api/historyNotebooks.ts` | API client |

### Reference (Don't Modify)

| File | Pattern |
|------|---------|
| `client/src/components/PageEditor/PageEditor.vue` | Editor integration |
| `client/src/components/Notifications/NotificationsList.vue` | List/message patterns |
| `client/src/components/Common/GCard.vue` | Card component |
| `client/src/composables/resourceWatcher.ts` | Polling pattern |
