# Asta

Asta is a set of skills for scientific research, usable by local coding agents. It is distributed as 
a set of agent plugins.

### asta-tools
A core set of skills for individual research tasks. Core capabilities include:

- **Literature Review** 
   - Intelligent search over full text of open-access publications, multi-paper summarization
   - Example request: _Our experiments have shown that task-driven learning progresses from high-level to low-level neuronal layers.
     Are there any studies that show learning in the opposite direction?_
- **Local Library Management**
  - Find and download PDFs from authenticated sources, extract contents, index for local retrieval
  - Example request: _Fetch the content of the papers in this BibTeX file and index them_
- **Data Analysis** - 
  - Run a series of data analysis experiments on a local dataset, using automatically-generated hypotheses
  - Example request: _This dataset contains neuropixel recordings from mice performing a visual/auditory context-switching task. The experimental setup is ... Analyze how neurons respond to stimuli, activity, behavioral state, and movement. Keep these questions in mind: ..._
- **Theory/Hypothesis Generation** - 
  - Synthesize theoretical explanations for phenomena described in the literature
  - Example request: _What drives lung adenocarcinomas without known RTK/RAS/RAF pathway driver alterations_ 

### asta-flows
A library of multi-step workflows. The agent will select an appropriate workflow and execute a series of actions using the `asta-tools` skills and other tools in the environment 

### asta-assistant
A long-range autonomous research assistant. Point the agent to a mission document containing background and directions to explore.
The agent will coordinate with the
user to pursue open questions in a long-range research plan.

### asta-dev
Skills for developers wishing to contribute to the `asta-tools` or `asta-flows` plugins 

## Installation

```commandline
# Whole plugin (skills + hooks) into your agent's native plugin system.
npx plugins add allenai/asta-plugins

# Skills only (loose skill files).
npx skills add allenai/asta-plugins -g

# Claude Code marketplace (alternative to npx plugins)
> /plugin marketplace add allenai/asta-plugins
> /plugin install asta-tools
> /plugin install asta-flows      # optional, for multi-step workflows
> /plugin install asta-assistant  # optional, for autonomous research
> /plugin install asta-dev        # optional, for contributors
```

## Asta CLI

The skills install an `asta` CLI tool, which has sub-commands for the various research functions.
The CLI can be used directly from the command line or invoked by agents via Bash commands. Some commands 
work on the local filesystem using your own LLM provider keys. Other commands call external APIs hosted by Ai2
For these, the CLI will prompt you to authenticate on first use.

## Research project documentation

The [`asta-tools:workspace`](plugins/asta-tools/skills/workspace/SKILL.md) skill lets users see and save the agent's work on a research project. Reports are generated with Quarto and
publised to GitHub Pages.

The `ghcr.io/allenai/asta` Docker image is published with the `asta` CLI, skills, and Quarto pre-installed 

```bash
docker pull ghcr.io/allenai/asta:v0.10.0

asta auth login
export ASTA_TOKEN=$(asta auth print-token --raw --refresh)

docker run --rm -it -e ASTA_TOKEN -e ANTHROPIC_API_KEY \
  ghcr.io/allenai/asta:latest bash

# Install Claude Code and register skills:
curl -fsSL https://claude.ai/install.sh | bash
claude plugin marketplace add /opt/asta-plugins --scope user
claude plugin install asta-tools

# Or install any other agent and use npx:
npx skills add /opt/asta-plugins -g --yes
```

## Development

See [DEVELOPER.md](DEVELOPER.md) for contributor guidelines, architecture details, and development setup.

## License

Apache 2.0
