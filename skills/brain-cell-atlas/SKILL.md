---
name: Allen Brain Cell Atlas
description: This skill should be used when the user asks about "brain cell types", "Allen Institute", "ABC Atlas", "cell type taxonomy", "brain-map.org", "CTKE", "MapMyCells", "MERFISH", "spatial transcriptomics in brain", "neuron types", "GABAergic", "glutamatergic", "brain region cell composition", "brain structure ontology", "brain region hierarchy", "cell electrophysiology", "cell morphology", "Allen Cell Types Database", or needs to answer questions grounded in the Allen Institute Brain Cell Atlas and neuroscience cell type literature.
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
- User asks about brain region anatomy, hierarchy, or structure ontology (e.g., "where is CA1?")
- User asks about electrophysiology or morphology data for specific cell types
- User needs human brain cell type data or cross-species comparisons

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

#### Cell Type Taxonomy (mouse + human)

| Command | Purpose | Example |
|---|---|---|
| `lookup <name>` | Find a cell type by name — returns hierarchy, markers, brain regions, cell counts | `lookup "Sst"` |
| `lookup <name> -s human` | Look up cell type in human brain taxonomy | `lookup "Oligodendrocyte" -s human` |
| `markers <name>` | Get marker genes for a cell type at any hierarchy level (mouse only) | `markers "L5 IT"` |
| `gene <symbol>` | Reverse lookup: which cell types express a gene? (mouse only) | `gene "Gad2"` |
| `region <region>` | List cell types found in a brain region (aggregated by subclass, mouse only) | `region "hippocampus"` |
| `hierarchy <level>` | List all entries at a taxonomy level | `hierarchy class` |
| `hierarchy <level> -s human` | Human taxonomy levels: supercluster, cluster, subcluster, neurotransmitter | `hierarchy supercluster -s human` |
| `search <term>` | Free-text search across all annotations | `search "dopamine"` |
| `search <term> -s both` | Search across mouse and human taxonomies | `search "astrocyte" -s both` |

**Mouse-only commands:** `markers`, `gene`, and `region` only work with the mouse taxonomy (which has marker gene annotations and anatomical data). For human cell types, use `lookup -s human`, `hierarchy -s human`, or `search -s human`.

#### Cell Type Nomenclature Resolution

| Command | Purpose | Example |
|---|---|---|
| `resolve <name>` | Map any cell type name to its canonical Allen taxonomy entry | `resolve "fast-spiking interneuron"` |
| `resolve <name> -r <region>` | Disambiguate by brain region | `resolve "basket cell" -r cortex` |

The `resolve` command bridges naming conventions — morphological names ("chandelier cell"), electrophysiological names ("fast-spiking interneuron"), transgenic line names ("X94 interneuron"), and colloquial names ("rosehip cell") all resolve to canonical Allen taxonomy entries. It reports `match_quality` as "exact", "partial", or "ambiguous" and flags when a term is ambiguous across brain regions.

**When to use `resolve` vs `lookup`:** Use `resolve` when the user provides a non-Allen name (e.g., from a paper or textbook). Use `lookup` when searching by Allen taxonomy names directly.

#### Brain Structure Ontology

| Command | Purpose | Example |
|---|---|---|
| `structure <name>` | Look up brain structures by name or acronym | `structure "hippocampus"` |
| `structure <name> -c` | Include direct children of the matched structure | `structure "Ammon's horn" -c` |
| `structure-path <name>` | Show the full path from root to a structure, plus siblings | `structure-path "CA1"` |

#### Cell Types Database (electrophysiology & morphology)

| Command | Purpose | Example |
|---|---|---|
| `specimen --id <id>` | Get full details for a specific specimen (includes web URL) | `specimen --id 485909730` |
| `specimen --region <acr>` | Filter specimens by brain region acronym | `specimen --region VISp` |
| `specimen --type <type>` | Filter by dendrite type (spiny/aspiny/sparsely spiny) | `specimen --type spiny` |
| `specimen --layer <n>` | Filter by cortical layer | `specimen --layer 5` |
| `specimen --has-morphology` | Only specimens with 3D reconstructions | `specimen --has-morphology` |
| `specimen --has-model` | Only specimens with GLIF computational models | `specimen --has-model` |
| `specimen --species <sp>` | Filter by species (mouse/human) | `specimen --species human` |

Filters can be combined: `specimen --region VISp --type spiny --layer 5 --has-morphology`. Running `specimen` with no filters returns all ~2,300 specimens.

All commands output JSON. Use `--limit N` (or `-l N`) to cap results. The `hierarchy` command supports `--filter` (or `-f`) to narrow by keyword.

### Choosing the Right Command

```
User question about cells
├── Uses a non-Allen name? (paper/textbook terminology)
│   └── resolve first, then use the canonical name with other commands
├── Needs definitive data? → Use abc_query.py
│   ├── "What type is X?" → lookup
│   ├── "What markers does X have?" → markers
│   ├── "What cells express gene Y?" → gene
│   ├── "What cells are in region Z?" → region
│   │   └── Want anatomy context? → also run structure-path on the region
│   ├── "List all X-level types" → hierarchy
│   ├── "Does the human brain have X?" → lookup -s human / hierarchy -s human
│   ├── "Compare mouse vs human X" → search -s both
│   ├── "Where is brain region Z?" → structure / structure-path
│   ├── "Ephys/morphology data for X?" → specimen
│   └── "Is X the same as Y?" → resolve both, compare canonical names
└── Needs interpretation/mechanisms? → Use asta papers search

### Translating User Questions to Queries

| User question | Command |
|---|---|
| "What type of cell is an Sst interneuron?" | `lookup "Sst"` |
| "What are the marker genes for L5 IT neurons?" | `markers "L5 IT"` |
| "Which cell types express Gad2?" | `gene "Gad2"` |
| "What cell types are in the hippocampus?" | `region "hippocampus"` |
| "List all GABAergic subclasses" | `hierarchy subclass -f GABA` |
| "How many parvalbumin cells are there?" | `lookup "parvalbumin"` |
| "What are the 34 cell classes in the mouse brain?" | `hierarchy class` |
| "Find dopaminergic cell types" | `search "dopamine"` |
| "What markers distinguish L5 IT subtypes?" | `markers "L5 IT"` (check `markers_within_subclass` field) |
| "Where is CA1 in the brain hierarchy?" | `structure-path "CA1"` |
| "What subregions does the hippocampus have?" | `structure "hippocampus" -c` |
| "Show me electrophysiology data for spiny cells in layer 5" | `specimen --type spiny --layer 5` |
| "Are there human oligodendrocyte subtypes?" | `lookup "Oligodendrocyte" -s human` |
| "What neurotransmitter types exist in the human brain?" | `hierarchy neurotransmitter -s human` |
| "Compare astrocytes across species" | `search "astrocyte" -s both` |
| "Get details for specimen 485909730" | `specimen --id 485909730` |
| "What cells have morphological reconstructions in visual cortex?" | `specimen --region VISp --has-morphology` |
| "What is a fast-spiking interneuron in Allen taxonomy?" | `resolve "fast-spiking interneuron"` |
| "Is a chandelier cell the same as an axo-axonic cell?" | `resolve "chandelier cell"` then `resolve "axo-axonic cell"` — both → Pvalb chandelier |
| "What is a basket cell?" (ambiguous) | `resolve "basket cell"` — returns disambiguation with 3 candidates |
| "What is a cortical basket cell?" | `resolve "basket cell" -r cortex` — resolves to Pvalb |
| "Map 'pyramidal tract neuron' to Allen nomenclature" | `resolve "pyramidal tract neuron"` → L5 ET CTX Glut |
| "What is the Allen name for a rosehip cell?" | `resolve "rosehip cell"` → Lamp5 LCP2 |

**Human taxonomy naming caveat:** The human taxonomy uses descriptive names (e.g., "MGE interneuron", "Upper-layer intratelencephalic") rather than marker-gene abbreviations (e.g., "Pvalb", "L2/3 IT"). Searching for "Pvalb" with `-s human` will return no results — use "MGE interneuron" or broader terms like "interneuron" instead.

### Output JSON Fields

**`lookup` (mouse):** `level`, `cluster_id`, `supertype`, `subclass`, `class`, `neurotransmitter`, `anatomical_annotation`, `neighborhood`, `marker_genes`, `merfish_markers`, `tf_markers`, `nt_markers`, `cell_count`

**`lookup -s human`:** `level`, `name`, `label`, `parent`, `cell_count`, `description`

**`markers`:** `level`, `name`, `neurotransmitter`, `marker_genes`, `tf_markers`, `markers_within_subclass` (supertype only), `merfish_markers` (cluster only)

**`gene`:** `level`, `name`, `subclass`, `class`, `neurotransmitter`, `marker_type`/`marker_types` — tells you *why* this gene is listed (subclass_marker, tf_marker, merfish_marker, nt_marker, etc.)

**`region`:** `subclass`, `class`, `neurotransmitter`, `cluster_count`, `total_cells`, `anatomical_annotations`

**`specimen`:** `specimen_id`, `name`, `species`, `brain_region`, `region_acronym`, `layer`, `dendrite_type`, `web_url`, `electrophysiology` (vrest, ri, tau, avg_firing_rate, etc.), `morphology` (reconstruction_type, number_bifurcations, etc.), `models_available`, `ccf_coordinates`

**`structure`:** `id`, `acronym`, `name`, `parent`, `depth`, `color`, optionally `children`

**`structure-path`:** `structure`, `path_from_root` (list), `siblings` (list)

**`resolve`:** `canonical`, `level`, `class`, `region`, `matched_alias`, `alias_source`, `match_type` (canonical_exact/alias/disambiguated_by_region), `match_quality` (exact/partial/ambiguous), `note`, `score`. When ambiguous: `ambiguous: true` with `disambiguation.candidates` listing all possible cell types and `disambiguation.hint` for how to resolve.

### Mouse ↔ Human Taxonomy Levels

The two species use different hierarchy level names:

| Mouse level | Human equivalent | Description |
|---|---|---|
| class (34) | supercluster (31) | Broadest grouping |
| subclass (338) | cluster (461) | Intermediate grouping |
| supertype (1,201) | — | Region-specific variants (mouse only) |
| cluster (5,322) | subcluster (461) | Finest resolution |
| — | neurotransmitter (20) | NT type assignment (human only) |

### Synonym Support

The tool automatically expands common neuroscience terms to their atlas abbreviations:

- dopamine/dopaminergic → Dopa, serotonin/serotonergic → Sero
- parvalbumin → Pvalb, somatostatin → Sst
- hippocampus → HIP, cortex → CTX, thalamus → TH, cerebellum → CB
- astrocyte → Astro, oligodendrocyte → Oligo, microglia → Immune
- glutamatergic/excitatory → Glut, gabaergic/inhibitory → GABA

### Data Sources

All data is public — no API keys or authentication required.

**Mouse taxonomy (S3):**
- **Base URL:** `https://allen-brain-cell-atlas.s3.us-west-2.amazonaws.com/metadata/WMB-taxonomy/20231215/`
- **Version:** WMB-taxonomy 20231215 (Yao et al. 2023)
- **Coverage:** 5,322 clusters, 1,201 supertypes, 338 subclasses, 34 classes across ~4 million cells

**Human taxonomy (S3):**
- **Base URL:** `https://allen-brain-cell-atlas.s3.us-west-2.amazonaws.com/metadata/WHB-taxonomy/20240330/`
- **Version:** WHB-taxonomy 20240330 (Siletti et al. 2023)
- **Coverage:** 461 subclusters, 461 clusters, 31 superclusters, 20 neurotransmitter types across ~3.4 million cells
- **Note:** Human taxonomy uses different naming (e.g., "MGE interneuron" not "Pvalb") and lacks marker gene annotations

**Brain structure ontology (API):**
- **Endpoint:** `https://api.brain-map.org/api/v2/structure_graph_download/1.json`
- **Coverage:** ~700 brain structures with full parent-child hierarchy

**Cell Types Database (API):**
- **Endpoint:** `https://api.brain-map.org/api/v2/data/query.json`
- **Coverage:** ~2,300 specimens with electrophysiology, morphology, and computational models
- **Species:** Mouse and human

**Cache location:** `~/.abc_atlas_cache/` (taxonomy files only; API queries are live)

### Agent SDK Integration

When building agents (e.g., with [Claude Agent SDK](https://github.com/anthropics/claude-agent-sdk-python)) that need brain cell type data, give the agent access to run `abc_query.py` as a tool:

```python
# Example: give an agent the ability to query the atlas
# The agent can shell out to abc_query.py and parse the JSON output
import subprocess, json

def query_brain_atlas(command: str, *args: str) -> dict:
    """Query the Allen Brain Cell Atlas, structure ontology, or cell types DB."""
    result = subprocess.run(
        ["python", "abc_query.py", command, *args],
        capture_output=True, text=True
    )
    return json.loads(result.stdout)

# Cell type lookup (mouse or human)
info = query_brain_atlas("lookup", "Pvalb")
human = query_brain_atlas("lookup", "Oligodendrocyte", "-s", "human")

# Marker genes
markers = query_brain_atlas("markers", "L5 IT")

# Brain region composition
region = query_brain_atlas("region", "hippocampus")

# Brain structure ontology
path = query_brain_atlas("structure-path", "CA1")

# Electrophysiology specimens
specimens = query_brain_atlas("specimen", "--region", "VISp", "--type", "spiny")
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
# 1. Get mouse cortical classes
python abc_query.py hierarchy class

# 2. Get human superclusters for comparison
python abc_query.py hierarchy supercluster -s human

# 3. Cross-species search for specific types
python abc_query.py search "astrocyte" -s both

# 4. For detailed comparison, search papers
asta papers search "human mouse cortex cell types cross-species conservation" \
  --year 2020- --limit 10 --fields title,abstract,year,authors,citationCount
```

Mouse uses marker-gene names (e.g., "Pvalb Gaba"), human uses descriptive names (e.g., "MGE interneuron"). Reference Bakken et al. 2021 for the foundational cross-species comparison.

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

### "Where is the dentate gyrus in the brain?"

```bash
# Get the full anatomical path
python abc_query.py structure-path "DG"

# See what subregions it contains
python abc_query.py structure "Dentate gyrus" -c
```

Returns: root → Basic cell groups → Cerebrum → Cerebral cortex → Cortical plate → Hippocampal formation → Hippocampal region → Dentate gyrus, plus subregions (molecular layer, polymorph layer, granule cell layer, etc.).

### "What electrophysiology data exists for mouse visual cortex interneurons?"

```bash
# Find aspiny (inhibitory) specimens in primary visual cortex
python abc_query.py specimen --region VISp --type aspiny --species mouse -l 10
```

Returns specimens with resting potential, input resistance, firing rate, adaptation index, f-I curve slope, and GLIF model availability. Use specimen IDs for deeper analysis.

### "Are there human brain cell recordings available?"

```bash
# Query for human specimens with morphological reconstructions
python abc_query.py specimen --species human --has-morphology -l 10
```

### "Which cell types express Gad2?"

```bash
# Reverse gene lookup — find all cell types where Gad2 is a marker
python abc_query.py gene "Gad2"
```

Returns subclasses, supertypes, and clusters where Gad2 is listed as a marker gene. The `marker_type` field tells you whether it's a cluster marker, TF marker, MERFISH marker, or neurotransmitter marker.

### "What cell types are in the thalamus?" (combining structure + region)

```bash
# 1. Understand the anatomy — what is the thalamus?
python abc_query.py structure-path "TH"

# 2. Get cell types in the thalamus
python abc_query.py region "TH"

# The structure acronym from step 1 feeds directly into the region query
```

Use `structure` or `structure-path` to resolve anatomy, then pass the acronym to `region` for cell type composition.

### "A paper mentions 'fast-spiking basket cells' — what are those in the Allen taxonomy?"

```bash
# Resolve the non-Allen name to the canonical taxonomy entry
python abc_query.py resolve "fast-spiking basket cell"
```

Returns: Pvalb (subclass), match_quality: partial (basket cells are one morphological subtype within the Pvalb subclass). The agent can then use `lookup "Pvalb"` or `markers "Pvalb"` for detailed data.

### "Is a chandelier cell the same as an axo-axonic cell?"

```bash
# Resolve both names
python abc_query.py resolve "chandelier cell"
python abc_query.py resolve "axo-axonic cell"
```

Both resolve to Pvalb chandelier (supertype) — they are the same cell type described by different naming conventions (morphology vs synaptic targeting).

### "Find papers about basket cells" (ambiguous term)

```bash
# 1. Check if the term is ambiguous
python abc_query.py resolve "basket cell"
# → ambiguous=true, 3 candidates: cortical PV+, cerebellar, hippocampal CCK+

# 2. If the user means cortical basket cells:
python abc_query.py resolve "basket cell" -r cortex
# → Pvalb (subclass)

# 3. Now search with both the canonical AND common names
asta papers search "parvalbumin basket cell cortex fast-spiking" \
  --year 2018- --limit 10 --fields title,abstract,year,authors
```

When a cell type name is ambiguous, always resolve first, then use both the canonical Allen name AND the user's original term in paper searches to maximize coverage across naming conventions.
