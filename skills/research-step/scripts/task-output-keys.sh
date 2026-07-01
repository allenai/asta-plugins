#!/usr/bin/env bash
# task-output-keys.sh <task_type> — print the space-separated output keys for a
# task from assets/schemas.yaml. The single schema reader for scripts:
# create-task.sh uses it to validate a task_type, validate-output.sh to get the
# expected output_json keys.
# Exit: 0 ok · 1 usage · 3 unknown task_type · 5 cannot read schema
#       (python3/PyYAML missing or schemas.yaml unreadable — run init)
set -euo pipefail
here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
schemas="$here/../assets/schemas.yaml"

[[ $# -eq 1 ]] || { echo "usage: task-output-keys.sh <task_type>" >&2; exit 1; }

python3 - "$schemas" "$1" <<'PY'
import sys

try:
    import yaml
except ImportError:
    print("task-output-keys: python3 cannot import yaml (PyYAML) - run the init workflow", file=sys.stderr)
    sys.exit(5)

try:
    with open(sys.argv[1]) as f:
        d = yaml.safe_load(f)
except Exception as e:
    print(f"task-output-keys: cannot read {sys.argv[1]}: {e}", file=sys.stderr)
    sys.exit(5)

tasks = d.get("tasks") or {}
t = tasks.get(sys.argv[2])
if t is None:
    print(f"task-output-keys: unknown task_type '{sys.argv[2]}'", file=sys.stderr)
    print(f"task-output-keys: known: {' '.join(sorted(tasks))}", file=sys.stderr)
    sys.exit(3)
print(" ".join(t["output"]))
PY
