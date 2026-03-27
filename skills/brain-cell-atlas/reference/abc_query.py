#!/usr/bin/env python3
"""
Allen Brain Cell Atlas Query Tool

Lightweight CLI for querying the Allen Brain Cell Atlas taxonomy data.
Downloads CSV/Excel files from the public S3 bucket on first run and caches locally.

Usage:
    python abc_query.py lookup "Sst"
    python abc_query.py markers "L5 IT"
    python abc_query.py region "CTX"
    python abc_query.py hierarchy class
    python abc_query.py hierarchy subclass --filter GABA
    python abc_query.py search "dopaminergic"

Dependencies: openpyxl (pip install openpyxl)
"""

import argparse
import csv
import json
import os
import sys
import urllib.request
from pathlib import Path

S3_BASE = "https://allen-brain-cell-atlas.s3.us-west-2.amazonaws.com/metadata/WMB-taxonomy/20231215"

FILES = {
    "pivoted": f"{S3_BASE}/views/cluster_to_cluster_annotation_membership_pivoted.csv",
    "terms_with_counts": f"{S3_BASE}/views/cluster_annotation_term_with_counts.csv",
    "cluster_counts": f"{S3_BASE}/cluster.csv",
    "annotations": f"{S3_BASE}/cl.df_CCN202307220.xlsx",
}

CACHE_DIR = Path.home() / ".abc_atlas_cache"

# Common synonyms -> atlas abbreviations
SYNONYMS = {
    "dopaminergic": "Dopa",
    "dopamine": "Dopa",
    "serotonergic": "Sero",
    "serotonin": "Sero",
    "cholinergic": "Chol",
    "glutamatergic": "Glut",
    "glutamate": "Glut",
    "gabaergic": "GABA",
    "inhibitory": "GABA",
    "excitatory": "Glut",
    "parvalbumin": "Pvalb",
    "somatostatin": "Sst",
    "astrocyte": "Astro",
    "astrocytes": "Astro",
    "oligodendrocyte": "Oligo",
    "oligodendrocytes": "Oligo",
    "microglia": "Immune",
    "hippocampus": "HIP",
    "hippocampal": "HIP",
    "cortex": "CTX",
    "cortical": "CTX",
    "thalamus": "TH",
    "thalamic": "TH",
    "hypothalamus": "HY",
    "hypothalamic": "HY",
    "cerebellum": "CB",
    "cerebellar": "CB",
    "midbrain": "MB",
    "hindbrain": "HB",
    "striatum": "STR",
    "striatal": "STR",
    "amygdala": "Amyg",
    "olfactory bulb": "OB",
}


def expand_synonyms(query: str) -> list[str]:
    """Return the query plus any synonym expansions."""
    queries = [query]
    lower = query.lower()
    if lower in SYNONYMS:
        queries.append(SYNONYMS[lower])
    return queries


def ensure_cached(name: str) -> Path:
    """Download a file from S3 if not already cached."""
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    filename = FILES[name].split("/")[-1]
    local_path = CACHE_DIR / filename
    if not local_path.exists():
        print(f"Downloading {filename}...", file=sys.stderr)
        urllib.request.urlretrieve(FILES[name], local_path)
    return local_path


def load_pivoted() -> list[dict]:
    """Load the flat cluster->hierarchy lookup table."""
    path = ensure_cached("pivoted")
    with open(path, newline="") as f:
        return list(csv.DictReader(f))


def load_terms_with_counts() -> list[dict]:
    """Load hierarchy terms with cell/cluster counts."""
    path = ensure_cached("terms_with_counts")
    with open(path, newline="") as f:
        return list(csv.DictReader(f))


def load_cluster_counts() -> dict[str, int]:
    """Load cluster alias -> cell count mapping."""
    path = ensure_cached("cluster_counts")
    with open(path, newline="") as f:
        return {row["cluster_alias"]: int(row["number_of_cells"]) for row in csv.DictReader(f)}


def load_annotations() -> dict:
    """Load the Excel annotations file. Returns dict of sheet_name -> list of row dicts."""
    try:
        import openpyxl
    except ImportError:
        print("Error: openpyxl is required. Install with: pip install openpyxl", file=sys.stderr)
        sys.exit(1)

    path = ensure_cached("annotations")
    wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
    result = {}
    for sheet_name in wb.sheetnames:
        ws = wb[sheet_name]
        rows = list(ws.iter_rows(values_only=True))
        if not rows:
            continue
        headers = [str(h) if h is not None else f"col_{i}" for i, h in enumerate(rows[0])]
        result[sheet_name] = [
            {h: v for h, v in zip(headers, row)} for row in rows[1:]
        ]
    wb.close()
    return result


def fuzzy_match(query: str, text: str) -> bool:
    """Case-insensitive substring match with synonym expansion."""
    text_lower = text.lower()
    for q in expand_synonyms(query):
        if q.lower() in text_lower:
            return True
    return False


def cmd_lookup(args):
    """Look up a cell type by name. Returns hierarchy, markers, and brain region."""
    query = args.query
    annotations = load_annotations()
    cluster_counts = load_cluster_counts()
    results = []

    # Search cluster-level annotations
    for row in annotations.get("cluster_annotation", []):
        searchable = " ".join(str(v) for v in [
            row.get("cluster_id_label", ""),
            row.get("supertype_label", ""),
            row.get("subclass_label", ""),
            row.get("class_label", ""),
            row.get("anatomical_annotation", ""),
            row.get("nt_type_label", ""),
        ])
        if fuzzy_match(query, searchable):
            cluster_alias = str(row.get("cluster_id", ""))
            cell_count = cluster_counts.get(cluster_alias, None)
            results.append({
                "level": "cluster",
                "cluster_id": row.get("cluster_id_label"),
                "supertype": row.get("supertype_id_label"),
                "subclass": row.get("subclass_id_label"),
                "class": row.get("class_id_label"),
                "neurotransmitter": row.get("nt_type_label"),
                "anatomical_annotation": row.get("anatomical_annotation"),
                "neighborhood": row.get("neighborhood"),
                "marker_genes": row.get("cluster.markers.combo"),
                "merfish_markers": row.get("merfish.markers.combo"),
                "tf_markers": row.get("cluster.TF.markers.combo"),
                "nt_markers": row.get("nt.markers"),
                "cell_count": cell_count,
            })

    # Search supertype-level
    for row in annotations.get("supertype_annotation", []):
        searchable = " ".join(str(v) for v in [
            row.get("supertype_id_label", ""),
            row.get("supertype_label", ""),
            row.get("subclass_label", ""),
            row.get("class_label", ""),
        ])
        if fuzzy_match(query, searchable):
            results.append({
                "level": "supertype",
                "supertype": row.get("supertype_id_label"),
                "subclass": row.get("subclass_id_label"),
                "class": row.get("class_id_label"),
                "marker_genes": row.get("supertype.markers.combo"),
                "markers_within_subclass": row.get("supertype.markers.combo (within subclass)"),
            })

    # Search subclass-level
    for row in annotations.get("subclass_annotation", []):
        searchable = " ".join(str(v) for v in [
            row.get("subclass_id_label", ""),
            row.get("subclass_label", ""),
            row.get("class_label", ""),
            row.get("nt_type_label", ""),
        ])
        if fuzzy_match(query, searchable):
            results.append({
                "level": "subclass",
                "subclass": row.get("subclass_id_label"),
                "class": row.get("class_id_label"),
                "neurotransmitter": row.get("nt_type_label"),
                "neighborhood": row.get("neighborhood"),
                "marker_genes": row.get("subclass.markers.combo"),
                "tf_markers": row.get("subclass.tf.markers.combo"),
            })

    # Search class-level
    for row in annotations.get("class_annotation", []):
        searchable = " ".join(str(v) for v in [
            row.get("class_id_label", ""),
            row.get("class_label", ""),
            row.get("neighborhood", ""),
        ])
        if fuzzy_match(query, searchable):
            results.append({
                "level": "class",
                "class": row.get("class_id_label"),
                "neighborhood": row.get("neighborhood"),
            })

    # Deduplicate: if we have many cluster hits for the same supertype, summarize
    if len(results) > args.limit:
        results = results[:args.limit]

    output = {"query": query, "total_matches": len(results), "results": results}
    print(json.dumps(output, indent=2, default=str))


def cmd_markers(args):
    """Return marker genes for a cell type at any hierarchy level."""
    query = args.query
    annotations = load_annotations()
    results = []

    # Check subclass level first (most useful)
    for row in annotations.get("subclass_annotation", []):
        searchable = f"{row.get('subclass_label', '')} {row.get('subclass_id_label', '')}"
        if fuzzy_match(query, searchable):
            results.append({
                "level": "subclass",
                "name": row.get("subclass_id_label"),
                "neurotransmitter": row.get("nt_type_label"),
                "marker_genes": row.get("subclass.markers.combo"),
                "tf_markers": row.get("subclass.tf.markers.combo"),
            })

    # Supertype level
    for row in annotations.get("supertype_annotation", []):
        searchable = f"{row.get('supertype_label', '')} {row.get('supertype_id_label', '')}"
        if fuzzy_match(query, searchable):
            results.append({
                "level": "supertype",
                "name": row.get("supertype_id_label"),
                "subclass": row.get("subclass_id_label"),
                "marker_genes": row.get("supertype.markers.combo"),
                "markers_within_subclass": row.get("supertype.markers.combo (within subclass)"),
            })

    # Cluster level
    for row in annotations.get("cluster_annotation", []):
        searchable = f"{row.get('cluster_id_label', '')} {row.get('supertype_label', '')}"
        if fuzzy_match(query, searchable):
            results.append({
                "level": "cluster",
                "name": row.get("cluster_id_label"),
                "supertype": row.get("supertype_id_label"),
                "marker_genes": row.get("cluster.markers.combo"),
                "merfish_markers": row.get("merfish.markers.combo"),
                "tf_markers": row.get("cluster.TF.markers.combo"),
            })

    if len(results) > args.limit:
        results = results[:args.limit]

    output = {"query": query, "total_matches": len(results), "results": results}
    print(json.dumps(output, indent=2, default=str))


def cmd_region(args):
    """List cell types found in a brain region."""
    query = args.query
    annotations = load_annotations()
    cluster_counts = load_cluster_counts()

    # Search by anatomical_annotation and CCF fields in cluster_annotation
    matches = []
    for row in annotations.get("cluster_annotation", []):
        anat = str(row.get("anatomical_annotation", ""))
        ccf_broad = str(row.get("CCF_broad.freq", ""))
        ccf_acr = str(row.get("CCF_acronym.freq", ""))
        if fuzzy_match(query, anat) or fuzzy_match(query, ccf_broad) or fuzzy_match(query, ccf_acr):
            matches.append(row)

    # Aggregate by subclass
    subclass_map = {}
    for row in matches:
        subclass = row.get("subclass_id_label", "unknown")
        if subclass not in subclass_map:
            subclass_map[subclass] = {
                "subclass": subclass,
                "class": row.get("class_id_label"),
                "neurotransmitter": row.get("nt_type_label"),
                "cluster_count": 0,
                "total_cells": 0,
                "anatomical_annotations": set(),
            }
        subclass_map[subclass]["cluster_count"] += 1
        alias = str(row.get("cluster_id", ""))
        subclass_map[subclass]["total_cells"] += cluster_counts.get(alias, 0)
        anat = row.get("anatomical_annotation")
        if anat:
            subclass_map[subclass]["anatomical_annotations"].add(str(anat))

    results = sorted(subclass_map.values(), key=lambda x: x["total_cells"], reverse=True)
    for r in results:
        r["anatomical_annotations"] = sorted(r["anatomical_annotations"])

    if len(results) > args.limit:
        results = results[:args.limit]

    output = {"query": query, "region_matches": len(results), "results": results}
    print(json.dumps(output, indent=2, default=str))


def cmd_hierarchy(args):
    """List all entries at a given taxonomy level."""
    level = args.level
    filter_term = args.filter
    annotations = load_annotations()

    sheet_map = {
        "class": "class_annotation",
        "subclass": "subclass_annotation",
        "supertype": "supertype_annotation",
        "cluster": "cluster_annotation",
    }

    if level not in sheet_map:
        print(f"Error: level must be one of: {', '.join(sheet_map.keys())}", file=sys.stderr)
        sys.exit(1)

    sheet = sheet_map[level]
    rows = annotations.get(sheet, [])

    label_key = f"{level}_id_label"
    results = []
    for row in rows:
        label = str(row.get(label_key, row.get(f"{level}_label", "")))
        if filter_term and not fuzzy_match(filter_term, label):
            # Also check class/neurotransmitter for filtering
            class_label = str(row.get("class_label", row.get("class_id_label", "")))
            nt_label = str(row.get("nt_type_label", ""))
            neighborhood = str(row.get("neighborhood", ""))
            if not any(fuzzy_match(filter_term, f) for f in [class_label, nt_label, neighborhood]):
                continue

        entry = {"name": label}
        if level == "subclass":
            entry["class"] = row.get("class_id_label")
            entry["neurotransmitter"] = row.get("nt_type_label")
            entry["neighborhood"] = row.get("neighborhood")
            entry["marker_genes"] = row.get("subclass.markers.combo")
        elif level == "supertype":
            entry["subclass"] = row.get("subclass_id_label")
            entry["class"] = row.get("class_id_label")
            entry["marker_genes"] = row.get("supertype.markers.combo")
        elif level == "class":
            entry["neighborhood"] = row.get("neighborhood")
        elif level == "cluster":
            entry["supertype"] = row.get("supertype_id_label")
            entry["subclass"] = row.get("subclass_id_label")
            entry["class"] = row.get("class_id_label")
            entry["anatomical_annotation"] = row.get("anatomical_annotation")

        results.append(entry)

    if len(results) > args.limit:
        results = results[:args.limit]

    output = {"level": level, "filter": filter_term, "total": len(results), "results": results}
    print(json.dumps(output, indent=2, default=str))


def cmd_search(args):
    """Free-text search across all cell type names and annotations."""
    query = args.query
    annotations = load_annotations()
    results = []

    # Search across all annotation levels
    for sheet_name, rows in annotations.items():
        if sheet_name in ("MERFISH_gene_panel", "Column header explanation"):
            continue
        for row in rows:
            all_text = " ".join(str(v) for v in row.values() if v is not None)
            if fuzzy_match(query, all_text):
                # Build a compact result
                entry = {"source": sheet_name}
                for key in ("cluster_id_label", "supertype_id_label", "supertype_label",
                            "subclass_id_label", "subclass_label", "class_id_label",
                            "class_label", "anatomical_annotation", "nt_type_label",
                            "neighborhood"):
                    if key in row and row[key] is not None:
                        entry[key.replace("_id_label", "").replace("_label", "")] = row[key]
                results.append(entry)

    # Deduplicate
    seen = set()
    unique = []
    for r in results:
        key = json.dumps(r, sort_keys=True, default=str)
        if key not in seen:
            seen.add(key)
            unique.append(r)

    if len(unique) > args.limit:
        unique = unique[:args.limit]

    output = {"query": query, "total_matches": len(unique), "results": unique}
    print(json.dumps(output, indent=2, default=str))


def main():
    parser = argparse.ArgumentParser(
        description="Query the Allen Brain Cell Atlas taxonomy",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s lookup "Sst"              Look up Sst cell types
  %(prog)s markers "L5 IT"           Get marker genes for L5 IT neurons
  %(prog)s region "hippocampus"      Cell types in hippocampus
  %(prog)s hierarchy class           List all 34 classes
  %(prog)s hierarchy subclass -f GABA  GABAergic subclasses
  %(prog)s search "dopamine"         Free-text search
        """,
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    # lookup
    p_lookup = subparsers.add_parser("lookup", help="Look up a cell type by name")
    p_lookup.add_argument("query", help="Cell type name to search for")
    p_lookup.add_argument("--limit", "-l", type=int, default=20, help="Max results (default: 20)")
    p_lookup.set_defaults(func=cmd_lookup)

    # markers
    p_markers = subparsers.add_parser("markers", help="Get marker genes for a cell type")
    p_markers.add_argument("query", help="Cell type name")
    p_markers.add_argument("--limit", "-l", type=int, default=20, help="Max results (default: 20)")
    p_markers.set_defaults(func=cmd_markers)

    # region
    p_region = subparsers.add_parser("region", help="List cell types in a brain region")
    p_region.add_argument("query", help="Brain region name or CCF acronym")
    p_region.add_argument("--limit", "-l", type=int, default=50, help="Max results (default: 50)")
    p_region.set_defaults(func=cmd_region)

    # hierarchy
    p_hier = subparsers.add_parser("hierarchy", help="List taxonomy entries at a level")
    p_hier.add_argument("level", choices=["class", "subclass", "supertype", "cluster"])
    p_hier.add_argument("--filter", "-f", default=None, help="Filter by keyword")
    p_hier.add_argument("--limit", "-l", type=int, default=100, help="Max results (default: 100)")
    p_hier.set_defaults(func=cmd_hierarchy)

    # search
    p_search = subparsers.add_parser("search", help="Free-text search across all annotations")
    p_search.add_argument("query", help="Search term")
    p_search.add_argument("--limit", "-l", type=int, default=30, help="Max results (default: 30)")
    p_search.set_defaults(func=cmd_search)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
