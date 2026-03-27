---
name: Allen Brain Cell Atlas
description: This skill should be used when the user asks about "brain cell types", "Allen Institute", "ABC Atlas", "cell type taxonomy", "brain-map.org", "CTKE", "MapMyCells", "MERFISH", "spatial transcriptomics in brain", "neuron types", "GABAergic", "glutamatergic", "brain region cell composition", or needs to answer questions grounded in the Allen Institute Brain Cell Atlas and neuroscience cell type literature.
allowed-tools:
  - Bash(asta papers *)
  - Bash(asta literature find *)
  - Bash(python* *abc_query.py *)
  - Bash(pip install openpyxl*)
  - TaskOutput
  - Bash(jq *)
---

# Allen Brain Cell Atlas Research

Domain-grounded literature search and cell type knowledge for the Allen Institute Brain Cell Atlas (ABC Atlas) ecosystem. Targets neuroscience researchers who know the domain and want precise, literature-backed answers.

## When to Use This Skill

- User asks about brain cell types, cell type taxonomies, or nomenclature
- User references the Allen Brain Cell Atlas, CTKE, MapMyCells, or brain-map.org
- User asks about spatial transcriptomics (MERFISH) in the brain
- User wants papers on cell type classification, brain region composition, or cross-species comparisons
- User needs to map between cell type names, classes, subclasses, or ontology terms
- User asks about gene markers for brain cell types

**Not for generic paper search** — use Semantic Scholar Lookup for non-atlas queries.

**Prefer atlas queries over literature search** when the user needs definitive cell type data (taxonomy, markers, brain regions, cell counts). Use literature search for interpretive questions (mechanisms, disease associations, cross-species comparisons).

## Atlas Data Query Tool

The `abc_query.py` tool queries the Allen Brain Cell Atlas taxonomy directly from the public S3 dataset. No API keys or large downloads required — it caches ~6MB of CSV/Excel files on first run.

### Installation

```bash
pip install openpyxl  # only dependency beyond stdlib
```

### Commands

The tool is located at `reference/abc_query.py` relative to this skill file. Use it with:

```bash
python /path/to/skills/brain-cell-atlas/reference/abc_query.py <command> [args]
```

| Command | Purpose | Example |
|---|---|---|
| `lookup <name>` | Find a cell type by name — returns hierarchy, markers, brain regions, cell counts | `lookup "Sst"` |
| `markers <name>` | Get marker genes for a cell type at any hierarchy level | `markers "L5 IT"` |
| `region <region>` | List cell types found in a brain region (aggregated by subclass) | `region "hippocampus"` |
| `hierarchy <level>` | List all entries at a taxonomy level (class/subclass/supertype/cluster) | `hierarchy class` |
| `search <term>` | Free-text search across all annotations | `search "dopamine"` |

All commands output JSON. Use `--limit N` (or `-l N`) to cap results. The `hierarchy` command supports `--filter` (or `-f`) to narrow by keyword.

### Translating User Questions to Queries

| User question | Command |
|---|---|
| "What type of cell is an Sst interneuron?" | `lookup "Sst"` |
| "What are the marker genes for L5 IT neurons?" | `markers "L5 IT"` |
| "What cell types are in the hippocampus?" | `region "hippocampus"` |
| "List all GABAergic subclasses" | `hierarchy subclass -f GABA` |
| "How many parvalbumin cells are there?" | `lookup "parvalbumin"` |
| "What are the 34 cell classes in the mouse brain?" | `hierarchy class` |
| "Find dopaminergic cell types" | `search "dopamine"` |
| "What markers distinguish L5 IT subtypes?" | `markers "L5 IT"` (check `markers_within_subclass` field) |

### Synonym Support

The tool automatically expands common neuroscience terms to their atlas abbreviations:

- dopamine/dopaminergic → Dopa, serotonin/serotonergic → Sero
- parvalbumin → Pvalb, somatostatin → Sst
- hippocampus → HIP, cortex → CTX, thalamus → TH, cerebellum → CB
- astrocyte → Astro, oligodendrocyte → Oligo, microglia → Immune
- glutamatergic/excitatory → Glut, gabaergic/inhibitory → GABA

### Data Source

All data comes from the Allen Brain Cell Atlas public S3 bucket (no auth required):
- **Base URL:** `https://allen-brain-cell-atlas.s3.us-west-2.amazonaws.com/metadata/WMB-taxonomy/20231215/`
- **Taxonomy version:** WMB-taxonomy 20231215 (Yao et al. 2023)
- **Coverage:** 5,322 clusters, 1,201 supertypes, 338 subclasses, 34 classes across ~4 million mouse brain cells
- **Cache location:** `~/.abc_atlas_cache/`

### Agent SDK Integration

When building agents (e.g., with [Claude Agent SDK](https://github.com/anthropics/claude-agent-sdk-python)) that need brain cell type data, give the agent access to run `abc_query.py` as a tool:

```python
# Example: give an agent the ability to query the atlas
# The agent can shell out to abc_query.py and parse the JSON output
import subprocess, json

def query_brain_atlas(command: str, query: str, limit: int = 20) -> dict:
    """Query the Allen Brain Cell Atlas taxonomy."""
    result = subprocess.run(
        ["python", "abc_query.py", command, query, "-l", str(limit)],
        capture_output=True, text=True
    )
    return json.loads(result.stdout)

# Cell type lookup
info = query_brain_atlas("lookup", "Pvalb")

# Marker genes
markers = query_brain_atlas("markers", "L5 IT")

# Brain region composition
region = query_brain_atlas("region", "hippocampus")
```

## Search Strategy

Brain atlas questions often fail with naive keyword searches. Use these strategies:

### Decompose questions into effective searches

| User asks about | Search terms to try |
|---|---|
| Cell types in a brain region | `"[region] cell types transcriptomics"`, `"[region] single cell RNA-seq"` |
| Specific cell class/subclass | `"[cell type name] marker genes"`, `"[cell type] transcriptomic"` |
| Cross-species comparison | `"cross-species [region] cell types"`, `"conserved cell types mammalian brain"` |
| Spatial organization | `"MERFISH [region]"`, `"spatial transcriptomics [region] cell types"` |
| Disease + cell types | `"[disease] cell type [region]"`, `"single-nucleus RNA-seq [disease]"` |
| Taxonomy/nomenclature | `"cell type taxonomy [species] brain"`, `"brain cell nomenclature"` |

### Key authors to search when results are sparse

These authors lead major Allen Institute brain atlas efforts:

- **Hongkui Zeng** — ABC Atlas lead, whole mouse brain taxonomy
- **Bosiljka Tasic** — mouse cortex transcriptomics, cell type classification
- **Ed Lein** — human brain atlas, cross-species studies
- **Xiaowei Zhuang** — MERFISH spatial transcriptomics inventor
- **Zizhen Yao** — whole mouse brain transcriptomic atlas
- **Trygve Bakken** — human brain cell types, cross-species conservation
- **Kimberly Smith** — cell type nomenclature, atlas infrastructure

### Landmark papers

When answering foundational questions, cite these high-impact works:

- **Yao et al. 2023 (Nature)** — "A high-resolution transcriptomic and spatial atlas of cell types in the whole mouse brain" — the ABC Atlas paper. DOI: `10.1038/s41586-023-06812-z`
- **Zhang et al. 2023 (Nature)** — MERFISH whole mouse brain spatial atlas. DOI: `10.1038/s41586-023-06808-9`
- **Siletti et al. 2023 (Science)** — Transcriptomic diversity of cell types across the adult human brain. DOI: `10.1126/science.add7046`
- **Bakken et al. 2021 (Nature)** — Cross-species primary motor cortex cell types (BICCN). DOI: `10.1038/s41586-021-03465-8`
- **Tasic et al. 2018 (Nature)** — Shared and distinct transcriptomic cell types across mouse cortical areas. DOI: `10.1038/s41586-018-0654-5`

## Domain Vocabulary

See [reference/taxonomy.md](reference/taxonomy.md) for the full cell type hierarchy (classes + subclasses) and ontology mappings.

Key terminology:
- **Class** (34 total) — broadest grouping, e.g., "Glutamatergic", "GABAergic", "Astrocyte"
- **Subclass** (338 total) — finer divisions, e.g., "L2/3 IT", "Pvalb", "Lamp5"
- **Supertype** (1,201 total) — region-specific variants of subclasses
- **Cluster** (5,322 total) — finest resolution, individual transcriptomic profiles
- **MERFISH** — Multiplexed Error-Robust Fluorescence In Situ Hybridization (spatial method)
- **scRNA-seq / snRNA-seq** — single-cell / single-nucleus RNA sequencing
- **CCF** — Allen Mouse Brain Common Coordinate Framework (3D reference atlas)
- **CL ontology** — Cell Ontology terms (e.g., CL:0000540 = neuron)
- **UBERON** — Anatomy ontology for brain regions

## Platform Resources

When users need to explore data or visualizations, direct them to:

| Resource | URL | Use for |
|---|---|---|
| ABC Atlas | brain-map.org/bkp/explore/abc-atlas | Interactive cell type visualization, gene expression, spatial maps |
| CTKE | brain-map.org/bkp/reference/cell-type-knowledge-explorer | Multi-modal cell type cards (expression, spatial, electrophysiology) |
| MapMyCells | brain-map.org/bkp/analyze/mapmycells | Mapping user data to Allen taxonomies |
| Taxonomy Index | brain-map.org/our-research/cell-types-taxonomies/taxonomies-index | List of all published cell type taxonomies |
| Cell Annotation Platform | celltype.info/search/datasets?tissue=brain | Community cell type annotations, CL/UBERON alignment |
| abc_atlas_access (Python) | alleninstitute.github.io/abc_atlas_access/intro.html | Programmatic access to atlas data (AbcProjectCache) |
| Taxonomy Schema | github.com/AllenInstitute/AllenInstituteTaxonomy/tree/main/schema | AnnData schema for taxonomy files |
| CTKE Viz Code | github.com/AllenInstitute/CTKE_viz | Plot generation code for CTKE visualizations |

## Example Workflows

### "What GABAergic cell types are in the mouse hippocampus?"

```bash
# 1. Query the atlas directly for definitive cell type data
python abc_query.py region "hippocampus" -l 20

# 2. Then search for papers for context and interpretation
asta papers search "GABAergic interneurons hippocampus mouse transcriptomics" \
  --year 2020- --limit 10 --fields title,abstract,year,authors,citationCount
```

The atlas query returns actual cell types with counts (CA1-ProS Glut, CA3 Glut, Vip Gaba, Sst Gaba, DG Glut, etc.). Use papers for context on spatial organization and function.

### "How do human and mouse cortical cell types compare?"

```bash
# Atlas data is mouse-only — use literature for cross-species questions
asta papers search "human mouse cortex cell types cross-species conservation" \
  --year 2020- --limit 10 --fields title,abstract,year,authors,citationCount

# Key BICCN paper
asta papers get "DOI:10.1038/s41586-021-03465-8" --fields title,abstract,authors,year,citationCount
```

Reference Bakken et al. 2021 as the foundational cross-species comparison.

### "What genes define L2/3 IT neurons?"

```bash
# 1. Get definitive marker genes from the atlas
python abc_query.py markers "L2/3 IT"

# 2. For deeper context, search papers
asta papers search "L2/3 IT neurons marker genes cortex" \
  --year 2018- --limit 10 --fields title,abstract,year,authors
```

The atlas query returns exact marker gene lists per supertype (e.g., subclass markers + distinguishing markers within subclass). Papers provide functional context.

### "What is a Pvalb chandelier cell?"

```bash
# Look up the cell type directly
python abc_query.py lookup "Pvalb chandelier"
```

Returns the full hierarchy (class: CTX-MGE GABA, subclass: Pvalb chandelier Gaba), marker genes, TF markers, and neurotransmitter markers. No paper search needed for basic identification.

### "List all non-neuronal cell types"

```bash
# List all 34 classes — non-neuronal are at the end
python abc_query.py hierarchy class

# Or search for specific types
python abc_query.py search "astrocyte"
python abc_query.py search "oligodendrocyte"
```
