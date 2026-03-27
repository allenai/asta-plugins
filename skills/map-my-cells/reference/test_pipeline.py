"""
Full MapMyCells pipeline test - based on examples/full_mapping_pipeline.ipynb
Creates synthetic reference data, precomputes stats, selects markers, and maps cells.
"""
import json
import pathlib
import subprocess
import sys
import tempfile

import anndata
import numpy as np
import scipy.sparse as scipy_sparse

WORK_DIR = pathlib.Path(tempfile.mkdtemp(prefix="mapmycells_test_"))
print(f"Working directory: {WORK_DIR}")

# ============================================================
# Step 1: Create synthetic reference (training) data
# ============================================================
print("\n=== Step 1: Creating synthetic reference data ===")

rng = np.random.default_rng(42)
n_genes = 90
n_cells = 2000
gene_names = [f"gene_{i}" for i in range(n_genes)]

# Define a 3-level taxonomy: 3 classes -> 5 subclasses -> 8 clusters
taxonomy = {
    "class_A": {
        "subclass_A1": ["cluster_1", "cluster_2"],
        "subclass_A2": ["cluster_3"],
    },
    "class_B": {
        "subclass_B1": ["cluster_4", "cluster_5"],
    },
    "class_C": {
        "subclass_C1": ["cluster_6", "cluster_7"],
        "subclass_C2": ["cluster_8"],
    },
}

# Assign cells to clusters
all_clusters = []
for cls in taxonomy.values():
    for sub in cls.values():
        all_clusters.extend(sub)

cells_per_cluster = n_cells // len(all_clusters)
cluster_labels = []
subclass_labels = []
class_labels = []
for cls_name, cls in taxonomy.items():
    for sub_name, clusters in cls.items():
        for clu in clusters:
            cluster_labels.extend([clu] * cells_per_cluster)
            subclass_labels.extend([sub_name] * cells_per_cluster)
            class_labels.extend([cls_name] * cells_per_cluster)

actual_n_cells = len(cluster_labels)

# Create expression matrix with cluster-specific patterns
X = rng.poisson(lam=2, size=(actual_n_cells, n_genes)).astype(np.float32)

# Add signal: each cluster has 5 "marker" genes with elevated expression
for i, clu in enumerate(all_clusters):
    marker_start = i * 5
    marker_end = marker_start + 5
    mask = [c == clu for c in cluster_labels]
    X[mask, marker_start:marker_end] += rng.poisson(lam=20, size=(sum(mask), 5))

# Build AnnData
import pandas as pd

obs = pd.DataFrame(
    {"class": class_labels, "subclass": subclass_labels, "cluster": cluster_labels},
    index=[f"cell_{i}" for i in range(actual_n_cells)],
)
var = pd.DataFrame(index=gene_names)

training_adata = anndata.AnnData(
    X=scipy_sparse.csr_matrix(X), obs=obs, var=var
)

training_path = WORK_DIR / "training_data.h5ad"
training_adata.write_h5ad(training_path)
print(f"  Created training data: {training_adata.shape[0]} cells x {training_adata.shape[1]} genes")
print(f"  Saved to: {training_path}")

# ============================================================
# Step 2: Precompute statistics
# ============================================================
print("\n=== Step 2: Precomputing statistics ===")

precomputed_path = WORK_DIR / "precomputed_stats.h5"
cmd = [
    sys.executable, "-m", "cell_type_mapper.cli.precompute_stats_scrattch",
    "--hierarchy", '["class", "subclass", "cluster"]',
    "--h5ad_path", str(training_path),
    "--normalization", "raw",
    "--output_path", str(precomputed_path),
    "--tmp_dir", str(WORK_DIR / "tmp"),
]
print(f"  Running: {' '.join(cmd[:4])} ...")
result = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
if result.returncode != 0:
    print(f"  STDERR: {result.stderr}")
    sys.exit(1)
print(f"  Precomputed stats saved to: {precomputed_path}")

# ============================================================
# Step 3: Reference marker selection
# ============================================================
print("\n=== Step 3: Selecting reference markers ===")

ref_markers_dir = WORK_DIR / "reference_markers"
cmd = [
    sys.executable, "-m", "cell_type_mapper.cli.reference_markers",
    "--precomputed_path_list", json.dumps([str(precomputed_path)]),
    "--output_dir", str(ref_markers_dir),
    "--tmp_dir", str(WORK_DIR / "tmp"),
    "--n_valid", "20",
]
print(f"  Running: {' '.join(cmd[:4])} ...")
result = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
if result.returncode != 0:
    print(f"  STDERR: {result.stderr}")
    sys.exit(1)
print(f"  Reference markers saved to: {ref_markers_dir}")

# Find the reference markers file (output_dir creates files inside it)
import glob
ref_marker_files = list(ref_markers_dir.glob("*.h5"))
if not ref_marker_files:
    print(f"  ERROR: No .h5 files found in {ref_markers_dir}")
    sys.exit(1)
ref_markers_path = ref_marker_files[0]
print(f"  Found reference markers file: {ref_markers_path.name}")

# ============================================================
# Step 4: Query marker selection
# ============================================================
print("\n=== Step 4: Selecting query markers ===")

query_markers_path = WORK_DIR / "query_markers.json"
cmd = [
    sys.executable, "-m", "cell_type_mapper.cli.query_markers",
    "--reference_marker_path_list", json.dumps([str(ref_markers_path)]),
    "--output_path", str(query_markers_path),
    "--n_per_utility", "10",
    "--tmp_dir", str(WORK_DIR / "tmp"),
]
print(f"  Running: {' '.join(cmd[:4])} ...")
result = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
if result.returncode != 0:
    print(f"  STDERR: {result.stderr}")
    sys.exit(1)
print(f"  Query markers saved to: {query_markers_path}")

# ============================================================
# Step 5: Create unlabeled test data
# ============================================================
print("\n=== Step 5: Creating unlabeled test data ===")

n_test = 8
test_X = np.zeros((n_test, n_genes), dtype=np.float32)
test_labels = []
for i, clu in enumerate(all_clusters):
    # Primary cluster signal
    marker_start = i * 5
    test_X[i, marker_start : marker_start + 5] = rng.poisson(lam=20, size=5)
    # Add noise from a secondary cluster
    secondary = (i + 1) % len(all_clusters)
    sec_start = secondary * 5
    test_X[i, sec_start : sec_start + 5] = rng.poisson(lam=5, size=5)
    test_X[i] += rng.poisson(lam=2, size=n_genes)
    test_labels.append(clu)

test_obs = pd.DataFrame(
    {"true_cluster": test_labels},
    index=[f"test_cell_{i}" for i in range(n_test)],
)
test_adata = anndata.AnnData(
    X=scipy_sparse.csr_matrix(test_X), obs=test_obs, var=var
)

test_path = WORK_DIR / "unlabeled_data.h5ad"
test_adata.write_h5ad(test_path)
print(f"  Created test data: {test_adata.shape[0]} cells x {test_adata.shape[1]} genes")

# ============================================================
# Step 6: Run hierarchical mapping
# ============================================================
print("\n=== Step 6: Running hierarchical mapping ===")

result_json_path = WORK_DIR / "mapping_result.json"
result_csv_path = WORK_DIR / "mapping_result.csv"
cmd = [
    sys.executable, "-m", "cell_type_mapper.cli.from_specified_markers",
    "--query_path", str(test_path),
    "--precomputed_stats.path", str(precomputed_path),
    "--query_markers.serialized_lookup", str(query_markers_path),
    "--extended_result_path", str(result_json_path),
    "--csv_result_path", str(result_csv_path),
    "--type_assignment.normalization", "raw",
    "--type_assignment.bootstrap_iteration", "100",
    "--type_assignment.bootstrap_factor", "0.5",
    "--type_assignment.n_processors", "2",
    "--cloud_safe", "False",
    "--tmp_dir", str(WORK_DIR / "tmp"),
]
print(f"  Running: {' '.join(cmd[:4])} ...")
result = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
if result.returncode != 0:
    print(f"  STDERR: {result.stderr}")
    sys.exit(1)
print(f"  Mapping complete!")

# ============================================================
# Step 7: Inspect results
# ============================================================
print("\n=== Step 7: Results ===")

# CSV results
print("\n--- CSV Output ---")
csv_text = result_csv_path.read_text()
for line in csv_text.split("\n")[:15]:
    print(f"  {line}")

# JSON results (summary)
print("\n--- JSON Output (first cell) ---")
with open(result_json_path) as f:
    json_result = json.load(f)

first_cell = json_result["results"][0]
print(f"  Cell: {first_cell.get('cell_id', 'N/A')}")
for level in ["class", "subclass", "cluster"]:
    assignment = first_cell.get(level, {})
    print(f"  {level}: {assignment.get('assignment', 'N/A')} "
          f"(prob={assignment.get('bootstrapping_probability', 'N/A')}, "
          f"corr={assignment.get('avg_correlation', 'N/A'):.3f})")

# Accuracy check
print("\n--- Accuracy Check ---")
correct = 0
total = len(json_result["results"])
for i, cell_result in enumerate(json_result["results"]):
    true_label = test_labels[i]
    predicted = cell_result.get("cluster", {}).get("assignment", "")
    match = "OK" if true_label == predicted else "MISS"
    if true_label == predicted:
        correct += 1
    print(f"  {test_labels[i]:>12s} -> {predicted:>12s} [{match}]")

print(f"\n  Accuracy: {correct}/{total} ({100*correct/total:.0f}%)")
print(f"\n=== Pipeline complete! Working dir: {WORK_DIR} ===")
