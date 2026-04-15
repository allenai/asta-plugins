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

## Workspace (Codespaces / Dev Containers)

For a pre-configured VS Code environment with Asta skills and Quarto, see the [Workspace skill](skills/workspace/SKILL.md).

## Development

See [DEVELOPER.md](DEVELOPER.md) for contributor guidelines, architecture details, and development setup.

## License

Apache 2.0
