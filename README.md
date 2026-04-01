# Asta — Nautilex 2026

Skills for searching papers that reference Allen Institute neuroscience datasets.

## Skills

- **Allen Dataset Search** — Search for papers referencing ABC Atlas, MERFISH, SEA-AD, and other Allen Institute datasets
- **Document Management** — Local document metadata index for tracking and searching papers

## Quick Start

### 1. Install the plugin

```commandline
# Claude Code only
> /plugin marketplace add allenai/asta-plugins@abc-atlas-search
> /plugin install asta-preview

# Any agent (Claude Code, Cursor, Copilot, etc.)
> Install skills from allenai/asta-plugins@abc-atlas-search
```

### 2. Bootstrap dataset indexes

Before searching, ask your agent:

> Bootstrap the Allen Institute search indexes

This downloads the pre-built indexes from S3 and warms the search cache. It will take 1-2 minutes for each dataset, but only needs to be done once per project directory.

### 3. Search

Ask your agent naturally — the skill activates automatically:

- "Find papers about cortical glutamatergic neurons in the ABC Atlas"
- "What SEA-AD papers discuss tau pathology in DLPFC?"
- "Search for MERFISH papers on spatial gene expression in mouse hippocampus"
- "Are there papers comparing cell types across the human cellular diversity and HMBA basal ganglia datasets?"
- "Find aging mouse brain papers published after 2023"

## Datasets

| Dataset | Description |
|---------|-------------|
| **ABC Atlas** | Mouse whole brain transcriptomics & spatial transcriptomics (10x scRNAseq, MERFISH) |
| **MERFISH Whole Mouse Brain** | Zhuang lab MERFISH spatial transcriptomics of whole mouse brain |
| **Cell-Mol Charac Aged Mouse** | Aging mouse brain transcriptomics |
| **Human Brain Cellular Diversity** | Human brain neuron and non-neuronal cell types (~375 clusters) |
| **SEA-AD** | Seattle Alzheimer's Disease Brain Cell Atlas |
| **HMBA Basal Ganglia** | Cross-species basal ganglia transcriptomics and spatial atlas |

## Implementation

The skills use the `asta` CLI, which wraps the `asta-documents` tool for indexed search over pre-built YAML indexes. Indexes are downloaded from S3 and cached locally. The CLI can be used directly or invoked by agents via Bash commands.

## License

Apache 2.0
