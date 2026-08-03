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
- **Feedback**
  - Interview-driven narrative report on how using Asta went, submitted (with optional supporting reports) to the Asta team
  - Example request: _Send the Asta team feedback about how this project went_

### asta-flows
A library of structured, multi-step research workflows. Give the agent a `mission.md` describing the
research to run; it plans and executes the work as a graph of typed, dependency-tracked tasks.

### asta-assistant
A long-range autonomous research assistant for open-ended, human-steered investigations. It works from a
`project.md` — a free-form project brief with background and open questions — and helps choose and pursue
the next unit of work with you.

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

## Documentation and Usage

Once installed, for information about how to use the plugins simply ask the LLM (e.g., Claude), e.g.,
* "Tell me about the asta-plugins"
* "How do I use the asta-plugins?"
  

## Getting started

Once installed, put the appropriate starting artifact in the workspace and prompt the agent:

- **Structured, multi-step research → `asta-flows`.** Give the agent a `mission.md` describing what to
  investigate and say _"Here's my mission document, begin."_ It routes to `asta-flows` and executes the
  work as a dependency-tracked task graph.
- **Open-ended, human-steered research → `asta-assistant`.** Give the agent a `project.md` project brief
  and ask _"What should I work on next on this project?"_ It routes to asta-assistant's `brainstorm`
  skill to select the next unit of work with you.

These entry points are pinned by the `asta_skills` routing eval in
[asta-bench-private#235](https://github.com/allenai/asta-bench-private/pull/235): `mission.md` must route
to `asta-flows` and `project.md` to `asta-assistant`, so the guidance above stays honest as the skills
evolve.

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
