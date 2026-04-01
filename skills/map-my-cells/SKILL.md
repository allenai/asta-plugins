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

## Mapping Cells (Stage 4)

For pre-built Allen taxonomies, reference files are already on S3. Only this command is needed:

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

For custom taxonomies (Stages 1–3) or on-the-fly markers, see `reference/mapping_cells.md`.

### Data Validation

Validate input H5AD files before mapping:

```bash
python -m cell_type_mapper.cli.validate_h5ad \
  --query_path input.h5ad \
  --valid_h5ad_path validated.h5ad
```

## Output Format

**CSV:** One row per cell with `{level}_label`, `{level}_name`, `{level}_bootstrapping_probability` columns.
**JSON:** Extended results with `assignment`, `bootstrapping_probability`, `avg_correlation`, `runner_up_assignment`, `directly_assigned`. See `reference/output.md` for full spec.

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

## Testing

Verify installation with the synthetic test pipeline: `python reference/test_pipeline.py`

For per-taxonomy S3 download URLs and CLI invocations, see `reference/running_online_taxonomies_locally.md`.

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
