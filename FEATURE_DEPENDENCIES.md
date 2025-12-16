# History Notebooks: Feature Dependency Diagram

## Legend

```
[Feature]     = UI/Frontend feature
(Backend)     = Backend prerequisite
───>          = Depends on
- - ->        = Soft dependency (can stub/mock)
║             = Parallel development possible
```

---

## Dependency Graph

```
                                    (Chat API)
                                        │
                                        │
                                        ▼
                              ┌─────────────────────┐
                              │  Split View + Chat  │
                              │    (Iteration 2)    │
                              └─────────────────────┘
                                        │
                                        │ depends on
                                        ▼
┌─────────────────┐           ┌─────────────────────┐           ┌─────────────────┐
│  Window Manager │           │   Agent Amendment   │           │   Revision UI   │
│   Integration   │           │      Workflow       │           │    (Phase 4)    │
└─────────────────┘           └─────────────────────┘           └─────────────────┘
        │                               │                               │
        │                               │                               │
        └───────────────┬───────────────┴───────────────────────────────┘
                        │ all depend on
                        ▼
              ┌─────────────────────┐
              │   Notebook View     │◄────────────────────────────────────┐
              │   (Full Page MVP)   │                                     │
              └─────────────────────┘                                     │
                   │         │                                            │
          ┌────────┘         └────────┐                                   │
          ▼                           ▼                                   │
┌─────────────────┐         ┌─────────────────┐         ┌─────────────────┐
│  HID Insertion  │         │  HID Preview/   │         │  Drag-and-Drop  │
│   (Toolbox)     │         │    Render       │         │   (Phase 5)     │
└─────────────────┘         └─────────────────┘         └─────────────────┘
          │                           │
          │                           │
          ▼                           ▼
┌─────────────────┐         ┌─────────────────┐
│ (markdown_parse │         │ (resolve_history│
│  hid= support)  │         │    _markdown)   │
└─────────────────┘         └─────────────────┘
          │                           │
          └───────────┬───────────────┘
                      ▼
              ┌─────────────────┐
              │ (HistoryNotebook│
              │  Model + API)   │
              └─────────────────┘
```

---

## Parallel Development Tracks

### Track A: Core Backend (Sequential)
```
1. HistoryNotebook + HistoryNotebookRevision models
2. API endpoints (CRUD)
3. markdown_parse.py: add hid= to ALLOWED_ARGUMENTS
4. markdown_util.py: resolve_history_markdown()
```

### Track B: Frontend MVP (After Track A items 1-2)
```
Can start once API exists, even if HID resolution incomplete:

1. HistoryNotebookView.vue (route, container)
2. HistoryNotebookEditor.vue (wraps MarkdownEditor)
3. History panel entry point
4. historyNotebookStore.ts
```

### Track C: HID Toolbox (After Track A item 3)
```
1. MarkdownDialog changes (emit hid=N)
2. directives.ts history_notebook mode
3. Scoped DataDialog (filter to current history)
```

### Track D: Independent Features (After Track B)
```
These can all proceed in parallel once MVP view exists:

D1. Window Manager Integration
    - Add displayOnly handling
    - Router title support

D2. Revision UI
    - NotebookRevisionList.vue
    - Grid config
    - (No diff viewer in MVP)

D3. Drag-and-Drop
    - History panel drag data
    - Editor drop handling
```

### Track E: Chat Integration (Blocked on Chat API)
```
1. ChatPanel.vue
2. Split view layout
3. Agent amendment workflow
4. edit_source tracking
```

---

## What's Actually MVP?

```
┌─────────────────────────────────────────────────────────┐
│                        MVP                              │
│                                                         │
│  ┌─────────────┐    ┌─────────────┐    ┌─────────────┐ │
│  │  Backend    │    │  View/Edit  │    │   HID       │ │
│  │  Model+API  │───>│  Component  │───>│  Insertion  │ │
│  └─────────────┘    └─────────────┘    └─────────────┘ │
│         │                  │                  │        │
│         ▼                  ▼                  ▼        │
│  ┌─────────────┐    ┌─────────────┐    ┌─────────────┐ │
│  │  HID parse  │    │  Route +    │    │  Toolbox    │ │
│  │  + resolve  │    │  Entry pt   │    │  changes    │ │
│  └─────────────┘    └─────────────┘    └─────────────┘ │
│                                                         │
└─────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────┐
│                    Post-MVP (Parallel)                  │
│                                                         │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌─────────┐ │
│  │ Window   │  │ Revision │  │ Drag &   │  │ Chat +  │ │
│  │ Manager  │  │ UI       │  │ Drop     │  │ Agent   │ │
│  └──────────┘  └──────────┘  └──────────┘  └─────────┘ │
│       ║             ║             ║         (blocked)  │
│       ╚═════════════╩═════════════╝                    │
│              Can develop in parallel                   │
│                                                         │
└─────────────────────────────────────────────────────────┘
```

---

## Extraction Features (Separate Track)

```
┌─────────────────────────────────────────────────────────┐
│                    Extraction                           │
│                                                         │
│  ┌─────────────────┐         ┌─────────────────┐       │
│  │ Extract to Page │         │ Extract to      │       │
│  │   (Simpler)     │         │ Workflow Report │       │
│  └─────────────────┘         └─────────────────┘       │
│           │                           │                 │
│           │                           │                 │
│           ▼                           ▼                 │
│  ┌─────────────────┐         ┌─────────────────┐       │
│  │ resolve_history │         │ HID → workflow  │       │
│  │ _markdown()     │         │ output mapping  │       │
│  └─────────────────┘         └─────────────────┘       │
│           │                           │                 │
│           └───────────┬───────────────┘                 │
│                       ▼                                 │
│              ┌─────────────────┐                        │
│              │ MVP Notebook    │                        │
│              │ (must exist)    │                        │
│              └─────────────────┘                        │
│                                                         │
└─────────────────────────────────────────────────────────┘
```

---

## Recommended Development Order

```
Week N:     [Backend Model + API] ─────────────────────────────┐
                     │                                         │
Week N+1:   [markdown_parse hid=] ──┬── [Frontend MVP View] ───┤
                     │              │           │               │
Week N+2:   [resolve_history_md] ───┤   [HID Toolbox] ─────────┤
                                    │           │               │
Week N+3:            ┌──────────────┴───────────┴──────┐       │
                     │        MVP COMPLETE             │       │
                     └─────────────────────────────────┘       │
                                    │                          │
Week N+4:   ┌───────────────────────┼───────────────────────┐  │
            │                       │                       │  │
            ▼                       ▼                       ▼  │
     [Window Manager]        [Revision UI]           [Drag-Drop]
            │                       │                       │  │
            └───────────────────────┴───────────────────────┘  │
                     Parallel, independent                     │
                                                               │
When ready: [Chat API merges] ─────────────────────────────────┘
                     │
                     ▼
            [Split View + Agent]
```

---

## Summary Table

| Feature | Depends On | Can Parallel With | Priority |
|---------|-----------|-------------------|----------|
| Backend Model+API | - | - | MVP |
| markdown_parse hid= | Model | Frontend View | MVP |
| resolve_history_markdown | hid= parse | - | MVP |
| Frontend View | API | hid= parse | MVP |
| HID Toolbox | hid= parse, View | resolve | MVP |
| Route + Entry Point | View | - | MVP |
| Window Manager | View | Revision, Drag | Post-MVP |
| Revision UI | View, API revisions | Window, Drag | Post-MVP |
| Drag-and-Drop | View, Toolbox | Window, Revision | Post-MVP |
| Extract to Page | resolve_history_md | - | Post-MVP |
| Extract to Workflow | resolve + mapping | Extract Page | Post-MVP |
| Chat + Agent | Chat API, View | - | Blocked |
