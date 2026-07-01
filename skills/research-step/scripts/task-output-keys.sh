#!/usr/bin/env bash
# task-output-keys.sh <task_type> — print the space-separated output keys for a
# step (task_type) from assets/workflows.yaml. The single schema reader for scripts:
# create-task.sh uses it to validate a task_type, validate-output.sh to get the
# expected output_json keys. Steps are defined inline inside loops' children.
# Exit: 0 ok · 1 usage · 3 unknown task_type · 5 cannot read schema
#       (python3/PyYAML missing or workflows.yaml unreadable — run init)
set -euo pipefail
here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
schemas="$here/../assets/workflows.yaml"

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

# Steps live inline inside loops; collect each step name -> its output keys by
# walking every loop's ordered children (a step has an `output` map; a sub-loop
# has `children`; a bare string is a reference).
steps = {}

def walk(loop_body):
    for item in loop_body.get("children") or []:
        if not isinstance(item, dict) or len(item) != 1:
            continue  # bare-name reference or malformed
        name, body = next(iter(item.items()))
        if not isinstance(body, dict):
            continue
        if "children" in body:
            walk(body)
        elif isinstance(body.get("output"), dict):
            steps.setdefault(name, [k[:-1] if k.endswith("?") else k for k in body["output"]])

for loop in (d.get("workflows") or {}).values():
    if isinstance(loop, dict):
        walk(loop)

t = steps.get(sys.argv[2])
if t is None:
    print(f"task-output-keys: unknown task_type '{sys.argv[2]}'", file=sys.stderr)
    print(f"task-output-keys: known: {' '.join(sorted(steps))}", file=sys.stderr)
    sys.exit(3)
print(" ".join(t))
PY
