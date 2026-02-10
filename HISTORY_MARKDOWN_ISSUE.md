# History Notebooks

> **Full Implementation Plan:** [HISTORY_MARKDOWN_PLAN.md](https://gist.github.com/jmchilton/da0dcbf266a60cc1b59308ed5e9d0ab9)

---

## The Problem

Galaxy histories capture computation but not understanding.

A history shows datasets and tool runs—the *what*. It doesn't capture:
- Why one approach was chosen over another
- Which results matter and which are noise
- The narrative connecting inputs to conclusions
- The iterative reasoning that led to insights

This gap becomes critical as AI agents enter the picture. Galaxy can already be controlled by agents—they can run tools, inspect outputs, and chain analyses. But where does the evolving understanding live? Where does the human-AI conversation about the data persist? Today, it evaporates when the chat session ends.

## The Vision

**History Notebooks are living documents that grow alongside your analysis.**

Just as a lab notebook captures the reasoning behind an experiment—not just the results—a history notebook captures the reasoning behind a computational analysis. What parameters did you try? Why did you choose this approach? Which outputs matter? The history notebook is Galaxy's answer to the lab notebook: a persistent, versioned record of scientific thinking tied to reproducible artifacts.

Each history gains associated notebooks—Galaxy-flavored markdown documents with full revision tracking, mirroring how Pages version content over time. The notebook embeds datasets, visualizations, and metadata directly. As analysis progresses—whether driven by human clicks, agent actions, or conversation between the two—the narrative builds up iteratively:

> "FastQC showed acceptable quality. Tried several mapping approaches—BWA with X=0.75 gave best results. Here's the comparison..."

...with live, rendered references to actual datasets, interactive Vega-Lite charts, and Galaxy visualization plugins.

This creates a "Claude Code for data analysis" experience. The agent doesn't just run tools—it builds up a polished document with rich visualizations, updates figures when parameters change, and refines the presentation in response to human feedback. The history notebook captures every iteration, tied to real artifacts.

## Two Paths to Publication

History Notebooks serve as the working document for analysis. When you're ready to share, two complementary paths exist:

### Publish Results → Pages

Extract the history notebook to a Galaxy Page—a permanent, shareable artifact. The Page preserves your narrative with all embedded objects resolved to their final state. Share a link; collaborators see the same visualizations, the same data tables, the same conclusions. Export to PDF for publication.

### Publish Methods → Workflows with Reports

Today, workflow extraction asks: *"What steps do you want to automate?"*

History notebooks flip this: *"What results do you want to present?"*

The user (or agent) focuses on building a compelling narrative around significant outputs. Galaxy traces back through the computational graph to determine what must run. The narrative becomes the workflow report, automatically translated from concrete HIDs to abstract workflow outputs.

Your history notebook—written with references like "dataset 42"—transforms into a report template with abstract references like "mapping_results". Run the workflow on new data and the report regenerates, accurate and complete.

## Why This Matters

### Analysis becomes a conversation, not a task list
Human and AI work together in a persistent medium. The human guides ("try different parameters", "that visualization is confusing"). The agent executes and documents. Understanding accumulates in the markdown.

### Rich documentation, not just text
Galaxy Markdown supports interactive Vega-Lite charts, Galaxy visualization plugins, and specialized viewers like Vitessce for spatial single-cell data. History notebooks make these tools available during iterative analysis—not just final reports.

### The narrative survives the session
Unlike chat transcripts that disappear, the history notebook persists alongside the data. Return to old work and find not just files, but the reasoning that produced them.

### Reproducible methods sections
Write your methods section as you work, with live references to actual datasets. When you extract a workflow, those concrete references translate to abstract outputs. Run the workflow on new data and the methods section regenerates—accurate, complete, reproducible.

## The User Journey

1. **Explore**: Run tools—manually, via agent, or both—generating results
2. **Narrate**: Build up the history notebook with findings, visualizations, and embedded dataset references
3. **Iterate**: Refine the analysis and presentation through human-AI collaboration
4. **Publish Results**: Extract to a Page for sharing polished conclusions
5. **Publish Methods**: Extract to a workflow; the narrative becomes a reproducible report template

---

## Executive Summary

### What We're Building

**History Notebooks** are markdown documents attached to Galaxy histories that capture the narrative and reasoning behind analyses—not just the data. **Each history can have multiple notebooks**, allowing users to create separate documents for different aspects of their analysis. Users document their work using Galaxy's rich markdown with embedded datasets, visualizations, and charts, all referenced by simple HID numbers (`hid=42`).

### Problem/Solution

| Problem | Solution |
|---------|----------|
| Histories show *what* was run, not *why* | Notebooks capture reasoning and interpretation |
| Chat/agent conversations disappear | Notebooks persist alongside the data |
| No "lab notebook" equivalent in Galaxy | Notebooks serve that role |
| Methods sections written after the fact | Notebooks enable write-as-you-go documentation |

**Strategic value:** Foundation for human-AI collaborative analysis. Agents can read, write, and amend notebooks—creating a persistent medium for AI-assisted science.

### Scope

#### MVP (Phases 1-4)
- Database models and API (multiple notebooks per history)
- HID-based markdown references (`hid=42` → dataset 42 in this history)
- Notebook list view + editor view
- Entry point from history panel
- Revision tracking (each save creates version)

#### Post-MVP (Phases 5-10)
- Window manager integration
- Revision browser UI
- Drag-and-drop from history panel
- Export to Page (shareable document)
- Export to Workflow Report (reproducible methods)
- Agent chat interface (blocked on Chat API)

### Architecture

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

### Technical Approach

#### Backend
- New models: `HistoryNotebook`, `HistoryNotebookRevision` (mirrors Page pattern, no unique constraint)
- API endpoints under `/api/histories/{id}/notebooks` (plural) + `/notebooks/{notebook_id}`
- Add `hid=` argument to existing markdown directives
- New `resolve_history_markdown()` function for HID→ID resolution

#### Frontend
- New routes: `/histories/:historyId/notebooks` (list) and `/notebooks/:notebookId` (editor)
- Reuse existing `MarkdownEditor` with new `mode="history_notebook"`
- Modify toolbox to emit `hid=N` instead of `history_dataset_id=N`
- Pinia store for notebook list + current notebook state

### Effort Estimate

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

### Dependencies

#### Internal
- Existing Galaxy markdown infrastructure (reused)
- Existing Page/PageRevision pattern (mirrored)
- Existing MarkdownEditor component (extended)

#### External
- **Chat API branch** (blocks Phase 10 only)

#### No New Dependencies
- No new Python packages
- No new JavaScript libraries
- No infrastructure changes

### Risks

| Risk | Mitigation |
|------|------------|
| HID resolution performance at scale | Index lookups, lazy loading |
| Large notebook content | TEXT column (no limit, matches Pages pattern) |
| Agent integration complexity | Isolated to Phase 10, can adjust scope |

### Success Criteria

#### MVP
- [ ] User can create **multiple notebooks** for any history they own
- [ ] User can view notebook list and switch between notebooks
- [ ] User can write markdown with `hid=` references
- [ ] User can insert references via toolbox
- [ ] Content persists across sessions
- [ ] Preview renders with resolved data

#### Post-MVP
- [ ] Export to Page works for all valid notebooks
- [ ] Export to Workflow generates valid report template
- [ ] Agent can read and propose changes to notebooks

---

## Design Alternatives

This section examines two key design questions and why History Notebooks takes its particular approach.

### Question 1: Why a Document, Not a Jupyter-like Interface?

#### The Notebook Paradigm Problem

Jupyter-style computational notebooks blend code, output, and narrative into an interactive execution environment. While powerful for exploration, this paradigm has significant problems for genomics and clinical settings.

##### Reproducibility Crisis

A [systematic study of 27,271 Jupyter notebooks from biomedical publications](https://academic.oup.com/gigascience/article/doi/10.1093/gigascience/giad113/7516267) found alarming results:
- Only **5.9%** of notebooks produced results matching the original
- Most failures due to missing dependencies, broken code, undocumented requirements
- Even well-intentioned authors struggle to create reproducible notebooks

The causes are structural:
- **Hidden state** - cells can execute in any order, creating invisible dependencies
- **Environment drift** - package versions change, breaking execution
- **Implicit assumptions** - data paths, credentials, and system dependencies go undocumented

##### Clinical/Regulatory Incompatibility

The [Australian Genomics NAGIM Implementation Recommendations](https://www.australiangenomics.org.au/wp-content/uploads/2021/06/Supplementary-Information-for-NAGIM-Implementation-Recommendations_January-2023.pdf) (Supplementary Information, January 2023) examines infrastructure requirements for clinical genomics in Australia. The document's analysis of production genomics workflows reveals why notebooks are not an appropriate paradigm for these settings:

- **Validation requirements** - Clinical labs require validated, version-controlled pipelines (CLIA, CAP accreditation)
- **Audit trails** - Regulatory compliance demands complete provenance, not interactive sessions
- **Reproducibility mandates** - Patient safety requires bit-identical reruns, not "works on my machine"

The [Design considerations for workflow management systems in production genomics research and the clinic](https://pmc.ncbi.nlm.nih.gov/articles/PMC8569008/) makes the case explicitly: production genomics requires workflow management systems (Nextflow, CWL, WDL) that separate execution from documentation.

##### The Right Tool for Each Job

| Concern | Notebooks | Document + WfMS |
|---------|-----------|-----------------|
| Reproducible execution | Poor (hidden state) | Excellent (declarative workflows) |
| Audit trails | Weak | Strong |
| Regulatory compliance | Difficult | Achievable |
| Narrative documentation | Good | Good |
| Human-AI collaboration | Session-bound | Persistent |
| Clinical validation | Impractical | Standard practice |

#### Why Documents Work Better

History Notebooks takes a **document-first approach**:

1. **Execution handled by Galaxy** - Tools run through Galaxy's validated, tracked execution engine
2. **Narrative in markdown** - Documentation lives in a versioned document, not interleaved with code
3. **References, not embedding** - HIDs point to artifacts; the document doesn't contain the computation
4. **Persistence over sessions** - The narrative survives; chat sessions can end

This separates concerns appropriately:
- Galaxy handles reproducible, auditable execution
- History Notebooks handles documentation, reasoning, and narrative
- Neither tries to be the other

#### Conclusion

The Jupyter paradigm optimizes for interactive exploration at the cost of reproducibility and auditability. For genomics settings—especially clinical ones—this tradeoff is unacceptable. A document-based approach lets Galaxy deliver the best of both worlds: validated execution infrastructure with rich, persistent documentation.

### Question 2: Why Not Just Use Galaxy Pages?

Galaxy already has Pages—shareable markdown documents with embedded datasets and visualizations. Why create History Notebooks?

#### An Honest Assessment

Many of the surface-level differences could be addressed with UI changes to Pages:

| Claimed Difference | Could Pages Be Modified? |
|-------------------|-------------------------|
| Reference style (HIDs vs absolute IDs) | Yes - Pages could accept HIDs |
| Working vs publishing distinction | Somewhat artificial - Pages can be drafts |
| Multiple documents per history | Already possible - create multiple Pages |
| Tied to specific history | Pages could add a history association |

If we're being honest, Pages *could* be extended to cover most History Notebook use cases. So why create something new?

#### The Real Differentiator: Workflow Extraction

The core architectural reason is **workflow extraction**—one of Galaxy's central tenets.

Galaxy's paradigm for reproducibility:
1. Run analysis interactively in a history
2. Extract a workflow from that history
3. The workflow captures the computational graph
4. Re-run on new data to reproduce the analysis

History Notebooks extend this paradigm to documentation:
1. Document analysis using HIDs (`hid=42`)
2. HIDs reference the same items used in workflow extraction
3. When extracting workflow, notebook content transforms into a report template
4. HIDs map to abstract workflow outputs (`output="mapping_results"`)

**Pages cannot participate in workflow extraction.** They use absolute IDs that reference specific datasets, not positions in a computational graph. A Page says "here's dataset abc123"—but that dataset doesn't exist when you run the workflow on new data.

#### Why This Matters

Consider documenting a methods section:

**In a Page:**
```
We aligned reads using BWA-MEM (history_dataset_id=abc123).
Quality metrics shown in history_dataset_id=def456.
```

This is useless for workflow extraction. The IDs point to specific datasets that won't exist in future runs.

**In a History Notebook:**
```
We aligned reads using BWA-MEM (hid=42).
Quality metrics shown in hid=38.
```

During workflow extraction, Galaxy traces the computational graph from these HIDs. The narrative transforms into:
```
We aligned reads using BWA-MEM (output="aligned_reads").
Quality metrics shown in output="alignment_qc".
```

Now the documentation travels with the workflow and regenerates correctly on new data.

#### The Architectural Choice

We could modify Pages to support HIDs, tie them to histories, and integrate with workflow extraction. But at that point, we'd have created History Notebooks inside Pages—adding complexity to an artifact designed for a different purpose.

The cleaner architecture:
- **Pages** remain the publication/sharing endpoint (absolute references, standalone)
- **History Notebooks** are the history-coupled working medium (HID references, workflow-extractable)
- Extraction flows naturally: History Notebook → Page *or* History Notebook → Workflow Report

#### Conclusion

The honest answer: Pages *could* be extended, but the workflow extraction integration is fundamental enough that it warrants a distinct artifact type. History Notebooks participate in Galaxy's core reproducibility paradigm; Pages intentionally sit outside it as stable publication endpoints.

### Design Alternatives Summary

| Question | Answer |
|----------|--------|
| Why not Jupyter-like? | Notebooks conflate execution and documentation. Clinical genomics requires separated, validated execution. Documents provide narrative without the reproducibility crisis. |
| Why not just Pages? | Pages could be extended, but workflow extraction is the key differentiator. HIDs participate in Galaxy's core reproducibility paradigm; absolute IDs don't. Cleaner to keep Pages as publication endpoints. |

History Notebooks provides a **document-based paradigm** appropriate for genomics settings—leveraging Galaxy's validated execution infrastructure while offering persistent, versioned documentation that participates in workflow extraction.

---

## Feature Dependencies

### Legend

```
[Feature]     = UI/Frontend feature
(Backend)     = Backend prerequisite
───>          = Depends on
- - ->        = Soft dependency (can stub/mock)
║             = Parallel development possible
```

### Dependency Graph

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

### Parallel Development Tracks

#### Track A: Core Backend (Sequential)
```
1. HistoryNotebook + HistoryNotebookRevision models
2. API endpoints (CRUD)
3. markdown_parse.py: add hid= to ALLOWED_ARGUMENTS
4. markdown_util.py: resolve_history_markdown()
```

#### Track B: Frontend MVP (After Track A items 1-2)
```
Can start once API exists, even if HID resolution incomplete:

1. HistoryNotebookView.vue (route, container)
2. HistoryNotebookEditor.vue (wraps MarkdownEditor)
3. History panel entry point
4. historyNotebookStore.ts
```

#### Track C: HID Toolbox (After Track A item 3)
```
1. MarkdownDialog changes (emit hid=N)
2. directives.ts history_notebook mode
3. Scoped DataDialog (filter to current history)
```

#### Track D: Independent Features (After Track B)
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

#### Track E: Chat Integration (Blocked on Chat API)
```
1. ChatPanel.vue
2. Split view layout
3. Agent amendment workflow
4. edit_source tracking
```

### What's Actually MVP?

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

### Extraction Features (Separate Track)

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

### Recommended Development Order

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

### Feature Summary Table

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

---

## Next Steps

1. Review and approve plan
2. Create GitHub issue(s) tracking implementation
3. Begin Phase 1 (backend foundation)
4. Parallel Phase 2 (frontend) once API exists

---

*The goal: transform Galaxy from a tool-execution platform into an interactive analysis environment where the history notebook is the persistent medium of human-AI collaboration—and the foundation for reproducible, publishable science.*
