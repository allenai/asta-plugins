# Asta

Asta is a set of skills for scientific research, usable by local coding agents.

## Installation

```commandline
# Whole plugin (skills + hooks) into your agent's native plugin system.
npx plugins add allenai/asta-plugins

# Skills only (loose skill files).
npx skills add allenai/asta-plugins -g

# Claude Code marketplace (alternative to npx plugins)
> /plugin marketplace add allenai/asta-plugins
> /plugin install asta-tools
```

### Skills

- **Semantic Scholar Lookup** - Quick paper/author lookups and metadata queries
- **Document Management** - Local document metadata index for tracking and searching papers
- **PDF Text Extraction** - Extract text from PDFs using olmOCR (cloud-based, no GPU required)
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
claude plugin install asta-tools

# Or install any other agent and use npx:
npx skills add /opt/asta-plugins -g --yes
```

## Research projects (Codespaces / Dev Containers / CI deploy)

The [`workspace`](plugins/asta-tools/skills/workspace/SKILL.md) skill lets users see and save the agent's work on a research project: scaffold infrastructure (Quarto, GitHub Pages auto-deploy with PR previews, devcontainer), show rendered work, save iterations.

## Benchmarking

[`agent-baselines`](https://github.com/allenai/agent-baselines) solvers (e.g. [`inspect-swe`](https://github.com/allenai/agent-baselines/tree/main/solvers/inspect-swe)) run Asta skills against any [Inspect](https://inspect.aisi.org.uk/)-compatible eval suite via `-S skills=<path>`: [Swapping in local skills](https://github.com/allenai/agent-baselines/tree/main/solvers/inspect-swe#swapping-in-local-skills) points it at the canonical `plugins/asta-tools/skills` tree (edit it directly). [Demo](https://github.com/allenai/agent-baselines/tree/main/solvers/inspect-swe#demo) is a worked example on [AstaBench](https://github.com/allenai/asta-bench), a scientific research suite for AI agents.

## Improving skills (or just reporting a problem)

Invoke the [`improve-skills`](plugins/asta-tools/skills/improve-skills/SKILL.md) skill if you:

- Observed an agent doing the wrong thing while using a skill (or not doing what you asked).
- Want an agent to be able to do something it currently can't (extend a skill, or add a new one).

Hand off at whatever depth you reach: a reported problem, a failing test for a fixer to pick up, or a fix you've validated with a paired eval.

Contributors changing a skill (including regression-checking before merging) follow the same workflow — see [DEVELOPER.md](DEVELOPER.md#validating-a-behavior-change).

## Development

See [DEVELOPER.md](DEVELOPER.md) for contributor guidelines, architecture details, and development setup.

## License

Apache 2.0
