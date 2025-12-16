# History Notebooks: Design Alternatives

This document examines two key design questions and why History Notebooks takes its particular approach.

---

## Question 1: Why a Document, Not a Jupyter-like Interface?

### The Notebook Paradigm Problem

Jupyter-style computational notebooks blend code, output, and narrative into an interactive execution environment. While powerful for exploration, this paradigm has significant problems for genomics and clinical settings.

#### Reproducibility Crisis

A [systematic study of 27,271 Jupyter notebooks from biomedical publications](https://academic.oup.com/gigascience/article/doi/10.1093/gigascience/giad113/7516267) found alarming results:
- Only **5.9%** of notebooks produced results matching the original
- Most failures due to missing dependencies, broken code, undocumented requirements
- Even well-intentioned authors struggle to create reproducible notebooks

The causes are structural:
- **Hidden state** - cells can execute in any order, creating invisible dependencies
- **Environment drift** - package versions change, breaking execution
- **Implicit assumptions** - data paths, credentials, and system dependencies go undocumented

#### Clinical/Regulatory Incompatibility

The [Australian Genomics NAGIM Implementation Recommendations](https://www.australiangenomics.org.au/wp-content/uploads/2021/06/Supplementary-Information-for-NAGIM-Implementation-Recommendations_January-2023.pdf) (Supplementary Information, January 2023) examines infrastructure requirements for clinical genomics in Australia. The document's analysis of production genomics workflows reveals why notebooks are not an appropriate paradigm for these settings:

- **Validation requirements** - Clinical labs require validated, version-controlled pipelines (CLIA, CAP accreditation)
- **Audit trails** - Regulatory compliance demands complete provenance, not interactive sessions
- **Reproducibility mandates** - Patient safety requires bit-identical reruns, not "works on my machine"

The [Design considerations for workflow management systems in production genomics research and the clinic](https://pmc.ncbi.nlm.nih.gov/articles/PMC8569008/) makes the case explicitly: production genomics requires workflow management systems (Nextflow, CWL, WDL) that separate execution from documentation.

#### The Right Tool for Each Job

| Concern | Notebooks | Document + WfMS |
|---------|-----------|-----------------|
| Reproducible execution | Poor (hidden state) | Excellent (declarative workflows) |
| Audit trails | Weak | Strong |
| Regulatory compliance | Difficult | Achievable |
| Narrative documentation | Good | Good |
| Human-AI collaboration | Session-bound | Persistent |
| Clinical validation | Impractical | Standard practice |

### Why Documents Work Better

History Notebooks takes a **document-first approach**:

1. **Execution handled by Galaxy** - Tools run through Galaxy's validated, tracked execution engine
2. **Narrative in markdown** - Documentation lives in a versioned document, not interleaved with code
3. **References, not embedding** - HIDs point to artifacts; the document doesn't contain the computation
4. **Persistence over sessions** - The narrative survives; chat sessions can end

This separates concerns appropriately:
- Galaxy handles reproducible, auditable execution
- History Notebooks handles documentation, reasoning, and narrative
- Neither tries to be the other

### Conclusion

The Jupyter paradigm optimizes for interactive exploration at the cost of reproducibility and auditability. For genomics settings—especially clinical ones—this tradeoff is unacceptable. A document-based approach lets Galaxy deliver the best of both worlds: validated execution infrastructure with rich, persistent documentation.

---

## Question 2: Why Not Just Use Galaxy Pages?

Galaxy already has Pages—shareable markdown documents with embedded datasets and visualizations. Why create History Notebooks?

### An Honest Assessment

Many of the surface-level differences could be addressed with UI changes to Pages:

| Claimed Difference | Could Pages Be Modified? |
|-------------------|-------------------------|
| Reference style (HIDs vs absolute IDs) | Yes - Pages could accept HIDs |
| Working vs publishing distinction | Somewhat artificial - Pages can be drafts |
| Multiple documents per history | Already possible - create multiple Pages |
| Tied to specific history | Pages could add a history association |

If we're being honest, Pages *could* be extended to cover most History Notebook use cases. So why create something new?

### The Real Differentiator: Workflow Extraction

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

### Why This Matters

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

### The Architectural Choice

We could modify Pages to support HIDs, tie them to histories, and integrate with workflow extraction. But at that point, we'd have created History Notebooks inside Pages—adding complexity to an artifact designed for a different purpose.

The cleaner architecture:
- **Pages** remain the publication/sharing endpoint (absolute references, standalone)
- **History Notebooks** are the history-coupled working medium (HID references, workflow-extractable)
- Extraction flows naturally: History Notebook → Page *or* History Notebook → Workflow Report

### Conclusion

The honest answer: Pages *could* be extended, but the workflow extraction integration is fundamental enough that it warrants a distinct artifact type. History Notebooks participate in Galaxy's core reproducibility paradigm; Pages intentionally sit outside it as stable publication endpoints.

---

## Summary

| Question | Answer |
|----------|--------|
| Why not Jupyter-like? | Notebooks conflate execution and documentation. Clinical genomics requires separated, validated execution. Documents provide narrative without the reproducibility crisis. |
| Why not just Pages? | Pages could be extended, but workflow extraction is the key differentiator. HIDs participate in Galaxy's core reproducibility paradigm; absolute IDs don't. Cleaner to keep Pages as publication endpoints. |

History Notebooks provides a **document-based paradigm** appropriate for genomics settings—leveraging Galaxy's validated execution infrastructure while offering persistent, versioned documentation that participates in workflow extraction.
