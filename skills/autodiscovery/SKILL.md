---
name: autodiscovery
description: Create, configure, and monitor AutoDiscovery runs — either via the hosted service (`asta autodiscovery`) or via the local CLI (`asta-autodiscovery`). Use when the user asks about their runs, experiments, discoveries, wants to check status, or wants to start a new discovery run.
metadata:
  internal: true
allowed-tools: Bash(asta autodiscovery *) Bash(asta auth *) Bash(asta-autodiscovery *) Bash(uv tool *) Bash(command -v *) Read(*) Write(*.json) TaskOutput
---

# AutoDiscovery

AutoDiscovery is an AI-driven scientific discovery platform that runs iterative experiments guided by Bayesian surprise and MCTS optimization.

This skill is a **router**. Inspect the user's request, pick one workflow, then read its `.md` file in `workflows/` and follow it. Do not execute a workflow from memory — always open the file first.

## Workflows

| Name | Purpose                                                                                                                                     | Detailed instructions |
|---|---------------------------------------------------------------------------------------------------------------------------------------------|---|
| **remote** | Use the hosted AutoDiscovery service via `asta autodiscovery`. Requires Asta auth and consumes credits; runs execute on Asta infrastructure. | `workflows/remote.md` |
| **local** | Run AutoDiscovery locally via the `asta-autodiscovery` CLI. Executes on the user's machine with user-provided API keys for making LLM calls | `workflows/local.md` |

## Routing

### 1. Honor explicit requests

- "local", "on my machine", "offline", "run it myself", or any reference to the `asta-autodiscovery` CLI → **local**.
- "remote", "hosted", "cloud", "Asta service", "my runs", "credits", or any reference to the `asta autodiscovery` (note the space) subcommand → **remote**.

### 2. Use signals when the request is ambiguous

- Past runs are stored in a local directory for **local** runs, or on the remote server for **remote** runs
- If the user is starting fresh and has not indicated a preference, ask which workflow they want before proceeding. Mention the tradeoff: remote uses Asta credentials and rate limits; local runs with the user's hardware and credentials.

### 3. No chaining

The two workflows are independent. Do not silently switch between them mid-task.
