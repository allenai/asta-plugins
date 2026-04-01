#!/usr/bin/env bash
# Bootstrap Allen Institute dataset indexes from S3.
#
# Downloads pre-built index.yaml files (and optionally full-text) for each
# dataset so that the allen-dataset-search skill can search them locally.
#
# Usage:
#   scripts/bootstrap-datasets.sh [OPTIONS] [DEST_DIR]
#
# Options:
#   --full-text     Also download full-text files (much larger)
#   --dataset NAME  Download only the named dataset (can repeat)
#   --dry-run       Show what would be downloaded without doing it
#   --help          Show this help message
#
# Arguments:
#   DEST_DIR        Destination directory (default: .asta/dataset-documents)
#
# Prerequisites:
#   - AWS CLI configured with access to s3://ai2-s2-public

set -euo pipefail

S3_BUCKET="ai2-s2-public"
S3_PREFIX="nautilex-2026/dataset-documents"

ALL_DATASETS=(
    abc-atlas
    cell-mol-charac
    hmba-basal-ganglia
    human-cellular-diversity
    merfish-whole-mouse-brain
    sea-ad
)

# --- Parse arguments ---

FULL_TEXT=false
DRY_RUN=false
SELECTED_DATASETS=()
DEST_DIR=""

while [[ $# -gt 0 ]]; do
    case "$1" in
        --full-text)
            FULL_TEXT=true
            shift
            ;;
        --dataset)
            SELECTED_DATASETS+=("$2")
            shift 2
            ;;
        --dry-run)
            DRY_RUN=true
            shift
            ;;
        --help|-h)
            sed -n '2,/^$/s/^# \?//p' "$0"
            exit 0
            ;;
        -*)
            echo "Unknown option: $1" >&2
            exit 1
            ;;
        *)
            DEST_DIR="$1"
            shift
            ;;
    esac
done

DEST_DIR="${DEST_DIR:-.asta/dataset-documents}"

if [[ ${#SELECTED_DATASETS[@]} -eq 0 ]]; then
    DATASETS=("${ALL_DATASETS[@]}")
else
    DATASETS=("${SELECTED_DATASETS[@]}")
fi

# --- Validate prerequisites ---

if ! command -v aws &>/dev/null; then
    echo "Error: AWS CLI not found. Install with: brew install awscli" >&2
    exit 1
fi

# --- Download ---

echo "Bootstrapping dataset indexes into ${DEST_DIR}/"
echo "Datasets: ${DATASETS[*]}"
if $FULL_TEXT; then
    echo "Including full-text files"
fi
echo

for dataset in "${DATASETS[@]}"; do
    s3_path="s3://${S3_BUCKET}/${S3_PREFIX}/${dataset}/"
    local_path="${DEST_DIR}/${dataset}/"

    echo "=== ${dataset} ==="

    if $DRY_RUN; then
        echo "  [dry-run] Would download ${s3_path}index.yaml → ${local_path}"
        if $FULL_TEXT; then
            echo "  [dry-run] Would download ${s3_path}full-text/ → ${local_path}full-text/"
        fi
        echo
        continue
    fi

    mkdir -p "${local_path}"

    # Always download index.yaml
    echo "  Downloading index.yaml..."
    aws s3 cp "${s3_path}index.yaml" "${local_path}index.yaml" --only-show-errors

    if $FULL_TEXT; then
        echo "  Downloading full-text/..."
        aws s3 sync "${s3_path}full-text/" "${local_path}full-text/" --only-show-errors
    fi

    # Show result
    size=$(wc -c < "${local_path}index.yaml" | tr -d ' ')
    echo "  Done (index: $(( size / 1024 ))K)"
    echo
done

echo "Bootstrap complete."
echo "Total datasets: ${#DATASETS[@]}"
if [[ -d "${DEST_DIR}" ]]; then
    du -sh "${DEST_DIR}" | awk '{print "Total size: " $1}'
fi
