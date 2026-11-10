"""Aggregate workspace jobs into a stable, skip-aware check result."""

import json
import os
import sys

needs = json.loads(os.environ["WORKSPACE_NEEDS"])
scope = needs.pop("scope")
workspace = scope.get("outputs", {}).get("workspace")
if scope["result"] != "success" or workspace not in ("true", "false"):
    sys.exit("Workspace scope did not succeed with a valid ownership decision")
if not needs:
    sys.exit("No workspace check results supplied")

expected = (
    "skipped"
    if os.environ["WORKSPACE_EVENT"] == "pull_request" and workspace == "false"
    else "success"
)
failed = []
for name, job in needs.items():
    result = job["result"]
    print(f"{name}: {result} (expected {expected})")
    if result != expected:
        failed.append(name)
if failed:
    sys.exit("Workspace checks did not complete as required: " + ", ".join(failed))
