# Asta

Asta is a set of skills for scientific research, usable by local coding agents.

## Skill Installation

```commandline
# Any agent (Claude Code, Cursor, Copilot, etc.)
npx skills add allenai/asta-plugins -g

# Claude Code only
> /plugin marketplace add allenai/asta-plugins
> /plugin install asta
```

### Skills

- **Semantic Scholar Lookup** - Quick paper/author lookups and metadata queries
- **Document Management** - Local document metadata index for tracking and searching papers
- **PDF Text Extraction** - Extract text from PDFs using olmOCR (cloud-based, no GPU required)

### Preview Skills

Install all with `--all`, or pick specific ones with `--skill "Name"`:

```commandline
# Any agent
npx skills add allenai/asta-plugins --all -g

# Claude Code only (auto-updates)
> /plugin install asta-preview
```

- **Find Literature** - General paper searching and citation finding
- **Literature Report Generation** - Comprehensive report writing with synthesis
- **Run Experiment** - Computational experiments with automated report generation
- **research step** - Autonomous research loop with iterative state tracking

Example user requests:
- "Find papers on RLHF"
- "Generate a literature review on transformers"
- "Get details for arXiv:2005.14165"
- "What papers cite the GPT-3 paper?"
- "Store this paper in Asta" / "Search my Asta documents for transformers"
- "Extract text from this PDF" / "OCR this document"
- "Run an experiment to test GPT-4 translation quality"

## Implementation

The skills install an `asta` CLI tool, which has sub-commands for the various research functions.
The CLI can be used directly from the command line or invoked by agents via Bash commands.

Some skills are pass-through commands to CLIs hosted in other repos. These are installed automatically
on first invocation.

Some skills are implemented by calling external APIs hosted by Ai2. For these, the CLI will prompt you to authenticate on first use.

## Docker Image

A Docker image with the `asta` CLI, skills, and Quarto pre-installed. Published to `ghcr.io/allenai/asta` on each release.

```bash
docker pull ghcr.io/allenai/asta:v0.10.0
```

Generate an `ASTA_TOKEN` on the host (one-time, expires after 30 days):

```bash
asta auth login
export ASTA_TOKEN=$(asta auth print-token --raw --refresh)
```

The source repo is at `/opt/asta-plugins` inside the image. Pass your
tokens, install your agent, and register skills:

```bash
docker run --rm -it -e ASTA_TOKEN -e ANTHROPIC_API_KEY \
  ghcr.io/allenai/asta:latest bash

# Install Claude Code and register skills:
curl -fsSL https://claude.ai/install.sh | bash
claude plugin marketplace add /opt/asta-plugins --scope user
claude plugin install asta-preview

# Or install any other agent and use npx:
npx skills add /opt/asta-plugins -g --all --yes
```

## Research projects (Codespaces / Dev Containers / CI deploy)

The [`workspace`](skills/workspace/SKILL.md) skill lets users see and save the agent's work on a research project: scaffold infrastructure (Quarto, GitHub Pages auto-deploy with PR previews, devcontainer), show rendered work, save iterations.

## Benchmarking

[`agent-baselines`](https://github.com/allenai/agent-baselines)'s [`inspect-swe`](https://github.com/allenai/agent-baselines/tree/main/solvers/inspect-swe) solver runs Asta skills against any [Inspect](https://inspect.aisi.org.uk/)-compatible eval suite via `-S skills=<path>`.

To run a benchmark, see [Demo](https://github.com/allenai/agent-baselines/tree/main/solvers/inspect-swe#demo), which runs the [`astabench`](https://github.com/allenai/asta-bench) science-agent suite with default skills. For your own edits, use [Swapping in local skills](https://github.com/allenai/agent-baselines/tree/main/solvers/inspect-swe#swapping-in-local-skills) (run `make build-plugins` first, then point at the regenerated tree).

For measuring the effect of a skill change, run a paired comparison via [Comparing two configurations](https://github.com/allenai/agent-baselines/tree/main/solvers/inspect-swe#comparing-two-configurations). Both arms must end up with the same `-S version=<cc-ver>` and same `ASTA_IMAGE=…@sha256:…`, so a typical flow is: run baseline with defaults, capture what resolved, pin the PR arm to match.

```bash
# 1. Run baseline arm — defaults (`:latest`, `version=auto`) are fine.
#    See the linked recipe above for the full `astabench eval` command;
#    swap in `-S skills=…/asta-plugins-baseline/…` and a baseline log dir.

# 2. Capture what resolved (these get reused in step 3):
eval "$(inspect log dump logs/baseline/*.eval | jq -er '.samples[0].metadata
    | "ASTA_IMAGE=\(.asta_image)\nAGENT_VERSION=\(.agent_version)"')"
export ASTA_IMAGE AGENT_VERSION

# 3. Run the PR arm. ASTA_IMAGE is read from the env (already exported), so
#    no flag is needed for the image. Add `-S version="$AGENT_VERSION"` and
#    the PR branch's `-S skills=…/asta-plugins/…`, into a different log dir.

# 4. Map the @sha256:… digest in $ASTA_IMAGE to a readable release tag
#    by matching the eval timestamp against this repo's release tags:
git tag --sort=-creatordate -l 'v*' | head
```

Record the pins in the PR description like `claude_code 2.1.142 · sonnet-4-6 · ghcr.io/allenai/asta:v0.17.2` (`@sha256:bf92d6a2…`) — tag for readability, digest for strict reproducibility.

See [#60](https://github.com/allenai/asta-plugins/pull/60) for a worked example against existing cases, and [#63](https://github.com/allenai/asta-plugins/pull/63) for a worked example of adding new per-skill cases.

When a comparison includes a configuration that isn't a regular commit on a PR branch (an ablation, an A/B variant, etc.), preserve it as an annotated git tag under `experiments/PR-<num>/<description>` so reviewers can check it out and reproduce. Tag after the PR is open so the number is known:

```bash
git tag -a experiments/PR-123/workspace-ablate-artifacts-tightening \
  -m "PR #123's workspace branch with skills/artifacts/SKILL.md reverted to main. Used to measure view_agent_output routing dependency on the artifacts tightening."
git push origin experiments/PR-123/workspace-ablate-artifacts-tightening
```

Tags survive branch deletion. Listable per-PR with `git tag -l 'experiments/PR-123/*'`. Link the tag from the PR description.

External contributors push the tag to their fork (no write access here) and link to the fork's tag URL — same convention, different remote.

## Development

See [DEVELOPER.md](DEVELOPER.md) for contributor guidelines, architecture details, and development setup.

## License

Apache 2.0
