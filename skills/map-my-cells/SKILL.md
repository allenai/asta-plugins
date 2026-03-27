---
name: MapMyCells
description: >-
  Use this skill when the user asks to "map cells", "map my cells", "cell type
  mapping", "MapMyCells", "assign cell types", "map to taxonomy", "map to Allen
  taxonomy", "hierarchical mapping", or needs to map unlabeled single-cell
  expression data onto a reference brain cell type taxonomy.
metadata:
  internal: true
allowed-tools:
  - Bash(command *)
  - Bash(python* *)
  - Bash(pip install *)
  - Read(pattern/*)
  - Write(pattern/*)
  - Edit(pattern/*)
  - TaskOutput
---

# MapMyCells

MapMyCells is the Allen Institute's open-source framework for mapping unlabeled single-cell omics data onto hierarchical reference brain cell type taxonomies. It uses marker-gene-based correlation and bootstrap voting to assign cells at every level of the taxonomy hierarchy, producing confidence scores (bootstrap probabilities) for each assignment.

**Citation:** Daniel, S.F. et al. "MapMyCells: High-performance mapping of unlabeled cell-by-gene data to reference brain taxonomies." *bioRxiv* (2026). doi:10.64898/2026.03.06.710160. The full paper is available at `reference/daniel_et_al_2026_mapmycells.pdf` for deeper questions about the algorithms, benchmarks, and use cases. Cite this paper when discussing MapMyCells results.

## Installation

```bash
pip install "cell_type_mapper@git+https://github.com/AllenInstitute/cell_type_mapper"
```

Requires Python >= 3.10 (tested with 3.12). Verify:

```bash
python -m cell_type_mapper.cli.from_specified_markers --help
```

## Supported Taxonomies

Four Allen Institute reference taxonomies are supported out of the box. Precomputed reference files are available on S3.

| Taxonomy | ID | Hierarchy | Size |
|----------|-----|-----------|------|
| Whole Mouse Brain | CCN20230722 | 34 classes → 338 subclasses → 1,201 supertypes → 5,322 clusters | 7M cells |
| Whole Human Brain | CCN20240330 | 31 superclusters → 461 clusters → 3,313 subclusters | 3M cells |
| Cross-species Basal Ganglia | CCN20250428 | 4 neighborhoods → 12 classes → 36 subclasses → 61 clusters | 1.8M cells |
| Human MTG SEA-AD | CCN20230505 | 3 classes → 24 subclasses → 139 supertypes | 1.4M cells |

See `reference/running_online_taxonomies_locally.md` for S3 download URLs and per-taxonomy CLI commands.

## Three Mapping Algorithms

| Algorithm | Use When | Speed |
|-----------|----------|-------|
| **Hierarchical** (default) | Cross-platform, cross-species mapping. Most robust. | Moderate |
| **Correlation** | Same-platform data mapped to same-platform reference. Simplest. | Fast |
| **Flat** | Skip hierarchy traversal. Single-pass to leaf level. | Fastest |

## Pipeline Overview

The full pipeline has 4 stages. For pre-built Allen taxonomies, **only Stage 4 is needed** (reference files already available on S3).

### Stage 1: Precompute Reference Statistics

From labeled reference data (H5AD), compute mean expression profiles per cell type.

```bash
python -m cell_type_mapper.cli.precompute_stats_scrattch \
  --hierarchy '["class", "subclass", "cluster"]' \
  --h5ad_path training_data.h5ad \
  --normalization raw \
  --output_path precomputed_stats.h5
```

### Stage 2: Reference Marker Selection

Identify all possible marker genes that discriminate between cell types at each taxonomy level.

```bash
python -m cell_type_mapper.cli.reference_markers \
  --precomputed_path_list '["precomputed_stats.h5"]' \
  --output_dir reference_markers/ \
  --n_valid 20
```

### Stage 3: Query Marker Selection

Downsample reference markers to an optimal subset using a greedy combinatorial algorithm.

```bash
python -m cell_type_mapper.cli.query_markers \
  --reference_marker_path_list '["reference_markers/reference_markers.h5"]' \
  --output_path query_markers.json \
  --n_per_utility 10
```

### Stage 4: Map Cells

Map unlabeled cells onto the taxonomy. This is the main command most users need.

```bash
python -m cell_type_mapper.cli.from_specified_markers \
  --query_path unlabeled_data.h5ad \
  --precomputed_stats.path precomputed_stats.h5 \
  --query_markers.serialized_lookup query_markers.json \
  --extended_result_path result.json \
  --csv_result_path result.csv \
  --type_assignment.normalization raw \
  --type_assignment.bootstrap_iteration 100 \
  --type_assignment.bootstrap_factor 0.5 \
  --type_assignment.n_processors 4 \
  --cloud_safe False
```

### Data Validation

Validate and normalize input H5AD files (ensures Ensembl gene IDs, integer counts):

```bash
python -m cell_type_mapper.cli.validate_h5ad \
  --query_path input.h5ad \
  --valid_h5ad_path validated.h5ad
```

### On-the-fly Markers (Small Taxonomies)

For small taxonomies where precomputed markers are unavailable, compute markers at runtime:

```bash
python -m cell_type_mapper.cli.map_to_on_the_fly_markers \
  --query_path unlabeled_data.h5ad \
  --precomputed_stats.path precomputed_stats.h5 \
  --extended_result_path result.json \
  --csv_result_path result.csv \
  --type_assignment.normalization raw \
  --query_markers.n_per_utility 15
```

## Output Format

**CSV output** contains one row per cell with columns for each taxonomy level:
- `{level}_label` — machine-readable node identifier
- `{level}_name` — human-readable name
- `{level}_bootstrapping_probability` — confidence (fraction of 100 bootstrap iterations that chose this assignment)

**JSON output** contains extended results per cell including:
- `assignment` — selected node at each level
- `bootstrapping_probability` — confidence metric
- `avg_correlation` — mean Pearson correlation with assigned type
- `runner_up_assignment` / `runner_up_probability` — next-best candidates
- `directly_assigned` — whether assignment was direct or inferred from hierarchy

See `reference/output.md` for complete field documentation.

## Interpreting Confidence

- **bootstrapping_probability >= 0.90**: High confidence. Assignment is reliable.
- **0.70 – 0.90**: Moderate confidence. Cell may be transitional or near a type boundary.
- **< 0.70**: Low confidence. Cell may be out-of-distribution, poor quality, or a novel type not in the reference.
- **avg_correlation < 0.3**: Possible out-of-distribution cell regardless of bootstrap probability.

## Input Requirements

- **Format:** H5AD (AnnData) or CSV
- **Matrix:** Cell-by-gene expression in `X` layer
- **Genes:** Gene identifiers in `var.index.values` must match the reference (typically Ensembl IDs for Allen taxonomies, or gene symbols for custom taxonomies)
- **Normalization:** Specify `raw` (integer counts) or `log2CPM` depending on your data
- **Size:** No inherent limit for local runs. Web app has 2 GB file limit.

## Example: Full Pipeline (Synthetic Data)

A complete test script is available at `reference/test_pipeline.py`. It creates synthetic reference data with a 3-level taxonomy (3 classes → 5 subclasses → 8 clusters), runs all 4 pipeline stages, and maps 8 test cells with 100% accuracy. Run it to verify your installation:

```bash
python reference/test_pipeline.py
```

Expected output: 8/8 cells correctly mapped with bootstrap probabilities > 0.80 at all taxonomy levels.

## Example: Mapping to Whole Mouse Brain (Pre-built)

Download reference files from S3 (one-time), then map:

```bash
# Download reference files (see reference/running_online_taxonomies_locally.md for URLs)
wget -P ~/.mapmycells/ <s3_url>/mouse_markers_230821.json
wget -P ~/.mapmycells/ <s3_url>/precomputed_stats_ABC_revision_230821.h5

# Map cells
python -m cell_type_mapper.cli.from_specified_markers \
  --query_path my_data.h5ad \
  --extended_result_path result.json \
  --csv_result_path result.csv \
  --drop_level CCN20230722_SUPT \
  --cloud_safe False \
  --query_markers.serialized_lookup ~/.mapmycells/mouse_markers_230821.json \
  --precomputed_stats.path ~/.mapmycells/precomputed_stats_ABC_revision_230821.h5 \
  --type_assignment.normalization raw \
  --type_assignment.n_processors 4
```

## Reference Materials

| File | Contents |
|------|----------|
| `reference/mapping_cells.md` | Complete CLI parameter reference for all commands |
| `reference/output.md` | Full output format specification with all fields |
| `reference/running_online_taxonomies_locally.md` | S3 download URLs and per-taxonomy CLI invocations |
| `reference/hierarchical_mapping.md` | Detailed algorithm description |
| `reference/test_pipeline.py` | End-to-end test script (synthetic data, ~2 min) |
| `reference/daniel_et_al_2026_mapmycells.pdf` | Full paper — algorithms, benchmarks, use cases |

## External Resources

| Resource | URL |
|----------|-----|
| GitHub repo | https://github.com/AllenInstitute/cell_type_mapper |
| MapMyCells web app | https://knowledge.brain-map.org/mapmycells/process/ |
| Example notebooks | https://github.com/AllenInstitute/cell_type_mapper/tree/main/examples |
| Allen Brain Cell Atlas | https://portal.brain-map.org/atlases-and-data/bkp/abc-atlas |
