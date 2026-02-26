---
name: generate-theories
description: Generates scientific theories from a research query using the Theorizer AI agent. Use when the user asks to "generate theories", "theorize about", "create hypotheses", "develop a theoretical framework", "what theories explain", or needs AI-generated scientific theories grounded in literature.
allowed-tools:
  - Bash(curl *)
  - Bash(python3 *)
  - Bash(pip install *)
  - Write($HOME/.asta/theories/*)
  - Read($HOME/.asta/theories/*)
  - Bash(jq *)
  - Bash(open *)
  - Bash(mkdir *)
  - TaskOutput
---

# Generate Theories

Generate scientific theories from a research query using the Theorizer A2A agent (arXiv:2601.16282).

## Two Modes

- **Literature-grounded** (default): Searches papers, extracts evidence, generates theories. ~30-35 min for 10 papers. Produces ~36 extraction + 4 theory artifacts.
- **Parametric**: Uses LLM knowledge only. ~5-8 min. Produces 4 theory artifacts.

Default to **literature mode with 10 papers** if the user doesn't specify.

## Workflow

1. Clarify the research query and determine mode (default: literature)
2. Create output directory:
   ```bash
   mkdir -p ~/.asta/theories/$(date +%Y-%m-%d-%H-%M-%S)-{slug}
   ```
3. Submit task via curl (run in background)
4. Poll until complete (run in background)
5. Install asta-sdk if needed
6. Export artifacts as HTML + JSON using asta-sdk
7. Present results with output folder path and open HTML index

## A2A Endpoint Protocol

### Submit Literature Task

```bash
curl -s REDACTED_MODAL_URL/ \
  -H 'Content-Type: application/json' -d '{
  "jsonrpc":"2.0","id":1,"method":"message/send",
  "params":{"message":{"role":"user","messageId":"msg-1","parts":[
    {"kind":"data","data":{"kind":"literature-theory-generation","data":{
      "theory_query":"QUERY","num_papers":10
    }}}
  ]}}
}'
```

### Submit Parametric Task

```bash
curl -s REDACTED_MODAL_URL/ \
  -H 'Content-Type: application/json' -d '{
  "jsonrpc":"2.0","id":1,"method":"message/send",
  "params":{"message":{"role":"user","messageId":"msg-1","parts":[
    {"kind":"data","data":{"kind":"parametric-theory-generation","data":{
      "theory_query":"QUERY"
    }}}
  ]}}
}'
```

### Response

The submit response returns a task object. Extract the task ID with:
```bash
echo "$RESPONSE" | jq -r '.result.id'
```

### Poll Task Status

```bash
curl -s REDACTED_MODAL_URL/ \
  -H 'Content-Type: application/json' -d '{
  "jsonrpc":"2.0","id":1,"method":"tasks/get",
  "params":{"id":"TASK_ID"}
}'
```

States: `submitted` → `working` → `completed` (or `failed`).

On completion, the response includes `result.artifacts[]`.

## Polling Pattern

Run polling in the background. Use 30s intervals for literature mode, 10s for parametric.

```bash
TASK_ID="..."
OUTPUT_DIR="$HOME/.asta/theories/..."
INTERVAL=30  # 30 for literature, 10 for parametric

while true; do
  RESULT=$(curl -s REDACTED_MODAL_URL/ \
    -H 'Content-Type: application/json' -d "{
    \"jsonrpc\":\"2.0\",\"id\":1,\"method\":\"tasks/get\",
    \"params\":{\"id\":\"$TASK_ID\"}
  }")
  STATE=$(echo "$RESULT" | jq -r '.result.status.state')
  if [ "$STATE" = "completed" ] || [ "$STATE" = "failed" ]; then
    echo "$RESULT" | jq '.result' > "$OUTPUT_DIR/task-result.json"
    echo "Task $STATE"
    break
  fi
  echo "Status: $STATE - polling again in ${INTERVAL}s..."
  sleep $INTERVAL
done
```

## Artifact Export

Install asta-sdk if not already available:
```bash
pip install "git+https://github.com/allenai/asta-sdk.git#subdirectory=src/sdk/python"
```

Export artifacts using Python:
```python
import json, os, sys
from asta.artifact import Artifact
from asta.artifact.exporter import export_artifacts_to_html_directory

output_dir = sys.argv[1]
d = json.load(open(os.path.join(output_dir, "task-result.json")))
arts_raw = d.get("artifacts", [])
seen, artifacts = set(), []
for a in arts_raw:
    data = a["parts"][0]["data"]
    aid = data.get("id", "")
    if aid not in seen:
        seen.add(aid)
        artifacts.append(Artifact.from_dict(data))

# Save individual JSON files
for art in artifacts:
    with open(os.path.join(output_dir, f"{art.id}.json"), "w") as f:
        f.write(art.to_json())

# Export HTML with cross-linking and index
html_dir = os.path.join(output_dir, "html")
export_artifacts_to_html_directory(artifacts, html_dir)
print(f"Exported {len(artifacts)} artifacts to {html_dir}")
```

## Output Structure

```
~/.asta/theories/YYYY-MM-DD-HH-MM-SS-{slug}/
├── task-result.json          # Raw A2A response
├── {artifact-id}.json        # Per-artifact JSON
├── html/
│   ├── index.html            # Artifact listing with links
│   └── {artifact-slug}.html  # Per-artifact HTML pages
```

## Timing Reference

| Mode | Papers | Duration | Artifacts |
|------|--------|----------|-----------|
| Parametric | N/A | ~5-8 min | 4 theories |
| Literature | 5 | ~15-20 min | ~20 extractions + 4 theories |
| Literature | 10 | ~30-35 min | ~36 extractions + 4 theories |

## Response Format Reference

Artifacts contain structured data with:
- **entities**: Papers with S2Metadata (title, authors, year, venue, abstract, tldr, citation counts)
- **annotations**: Snippets and facets linking evidence to entities
- **content**: Sections with markdown text, figures, and code blocks
