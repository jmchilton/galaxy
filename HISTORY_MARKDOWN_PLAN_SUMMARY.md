# History Notebooks: Executive Summary

## What We're Building

**History Notebooks** are markdown documents attached to Galaxy histories that capture the narrative and reasoning behind analyses—not just the data. **Each history can have multiple notebooks**, allowing users to create separate documents for different aspects of their analysis. Users document their work using Galaxy's rich markdown with embedded datasets, visualizations, and charts, all referenced by simple HID numbers (`hid=42`).

## Why It Matters

| Problem | Solution |
|---------|----------|
| Histories show *what* was run, not *why* | Notebooks capture reasoning and interpretation |
| Chat/agent conversations disappear | Notebooks persist alongside the data |
| No "lab notebook" equivalent in Galaxy | Notebooks serve that role |
| Methods sections written after the fact | Notebooks enable write-as-you-go documentation |

**Strategic value:** Foundation for human-AI collaborative analysis. Agents can read, write, and amend notebooks—creating a persistent medium for AI-assisted science.

---

## Scope

### MVP (Phases 1-4)
- Database models and API (multiple notebooks per history)
- HID-based markdown references (`hid=42` → dataset 42 in this history)
- Notebook list view + editor view
- Entry point from history panel
- Revision tracking (each save creates version)

### Post-MVP (Phases 5-10)
- Window manager integration
- Revision browser UI
- Drag-and-drop from history panel
- Export to Page (shareable document)
- Export to Workflow Report (reproducible methods)
- Agent chat interface (blocked on Chat API)

---

## Architecture

```
┌─────────────────────────────────────────────────────────┐
│                       History                            │
│                          │                              │
│     ┌────────────────────┼────────────────────┐         │
│     ▼                    ▼                    ▼         │
│  ┌──────────┐      ┌──────────┐         ┌──────────┐   │
│  │ Notebook │      │ Notebook │   ...   │ Notebook │   │
│  │    #1    │      │    #2    │         │    #N    │   │
│  │ hid=42   │      │ hid=38   │         │ hid=...  │   │
│  └──────────┘      └──────────┘         └──────────┘   │
└─────────────────────────────────────────────────────────┘
                          │
        ┌─────────────────┼─────────────────┐
        ▼                 ▼                 ▼
   ┌─────────┐      ┌──────────┐      ┌──────────┐
   │  Page   │      │ Workflow │      │  Agent   │
   │ Export  │      │  Report  │      │   Chat   │
   └─────────┘      └──────────┘      └──────────┘
   (Shareable)     (Reproducible)    (Collaboration)
```

**Key design choices:**
- **Multiple notebooks per history** - each history can have many notebooks
- Store HIDs in notebook, resolve to internal IDs at render time (human-readable, portable)
- Soft-delete pattern with deleted/purged flags (standard Galaxy pattern)
- Default title to history name, allow user override
- No content size limit (matches Pages)

---

## Technical Approach

### Backend
- New models: `HistoryNotebook`, `HistoryNotebookRevision` (mirrors Page pattern, no unique constraint)
- API endpoints under `/api/histories/{id}/notebooks` (plural) + `/notebooks/{notebook_id}`
- Add `hid=` argument to existing markdown directives
- New `resolve_history_markdown()` function for HID→ID resolution

### Frontend
- New routes: `/histories/:historyId/notebooks` (list) and `/notebooks/:notebookId` (editor)
- Reuse existing `MarkdownEditor` with new `mode="history_notebook"`
- Modify toolbox to emit `hid=N` instead of `history_dataset_id=N`
- Pinia store for notebook list + current notebook state

---

## Effort Estimate

| Phase | Description | Complexity | Parallel? |
|-------|-------------|------------|-----------|
| 1 | Backend models + API | Medium | No (foundation) |
| 2 | Frontend MVP view | Medium | After 1.1-1.2 |
| 3 | HID toolbox integration | Low-Medium | After 1.4 |
| 4 | Integration testing | Low | After 1-3 |
| **MVP Total** | | | |
| 5 | Window manager | Low | Yes |
| 6 | Revision UI | Medium | Yes |
| 7 | Drag-and-drop | Low | Yes |
| 8 | Page extraction | Medium | After MVP |
| 9 | Workflow report extraction | High | After 8 |
| 10 | Agent chat | High | Blocked on Chat API |

---

## Dependencies

### Internal
- Existing Galaxy markdown infrastructure (reused)
- Existing Page/PageRevision pattern (mirrored)
- Existing MarkdownEditor component (extended)

### External
- **Chat API branch** (blocks Phase 10 only)

### No New Dependencies
- No new Python packages
- No new JavaScript libraries
- No infrastructure changes

---

## Risks

| Risk | Mitigation |
|------|------------|
| HID resolution performance at scale | Index lookups, lazy loading |
| Large notebook content | TEXT column (no limit, matches Pages pattern) |
| Agent integration complexity | Isolated to Phase 10, can adjust scope |

---

## Success Criteria

### MVP
- [ ] User can create **multiple notebooks** for any history they own
- [ ] User can view notebook list and switch between notebooks
- [ ] User can write markdown with `hid=` references
- [ ] User can insert references via toolbox
- [ ] Content persists across sessions
- [ ] Preview renders with resolved data

### Post-MVP
- [ ] Export to Page works for all valid notebooks
- [ ] Export to Workflow generates valid report template
- [ ] Agent can read and propose changes to notebooks

---

## Next Steps

1. Review and approve plan
2. Create GitHub issue(s) tracking implementation
3. Begin Phase 1 (backend foundation)
4. Parallel Phase 2 (frontend) once API exists

---

## Reference Documents

| Document | Purpose |
|----------|---------|
| `THE_PROBLEM_AND_GOAL.md` | Vision and motivation |
| `RESEARCH_FOR_PLANNING.md` | Backend technical research |
| `RESEARCH_FOR_PLANNING_UX.md` | Frontend/UX research |
| `FEATURE_DEPENDENCIES.md` | Dependency diagram |
| `HISTORY_MARKDOWN_PLAN.md` | Detailed implementation plan |
