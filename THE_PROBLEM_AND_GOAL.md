# History Notebooks: A Shared Workspace for Human-AI Analysis

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

Each history gains an associated notebook—a Galaxy-flavored markdown document with full revision tracking, mirroring how Pages version content over time. The notebook embeds datasets, visualizations, and metadata directly. As analysis progresses—whether driven by human clicks, agent actions, or conversation between the two—the narrative builds up iteratively:

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

*The goal: transform Galaxy from a tool-execution platform into an interactive analysis environment where the history notebook is the persistent medium of human-AI collaboration—and the foundation for reproducible, publishable science.*
