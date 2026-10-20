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
Research workflows the agent plans with you and carries out using local tools: `theorize`, `auto-discovery` and `s2`. Start one with `/run-workflow`.

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

`asta-flows`, `asta-assistant` and `asta-dev` require `asta-tools`. Claude Code
installs it as a dependency. The default `npx plugins add` and `npx skills add`
commands install all four groups. For selective npx installs, include
`asta-tools` alongside the layer you select.

The CLI requires Python 3.11+ and `uv`. Its security-patched `cryptography`
50.0.0 dependency has no Intel macOS or 32-bit Windows wheels. On Intel macOS,
installation falls back to a source build requiring Xcode command-line tools,
Rust 1.83+ and OpenSSL 3+; see the [upstream build instructions](https://cryptography.io/en/50.0.0/installation/#building-cryptography-on-macos).
Upstream [no longer supports these platforms](https://cryptography.io/en/50.0.0/changelog/#v49-0-0),
and Asta's CI does not validate Intel macOS source builds. On Windows, use
64-bit Python. Downgrading below 50.0.0 to regain a wheel would restore a
security vulnerability fixed by this upgrade.

## Documentation and Usage

Once installed, for information about how to use the plugins simply ask the LLM (e.g., Claude), e.g.,
* "Tell me about the asta-plugins"
* "How do I use the asta-plugins?"

For GitHub/Slack integration, see [here](https://github.com/allenai/asta-plugins/tree/main/plugins/asta-dev) (Ai2 internal users only)
  
## Asta CLI

The skills install an `asta` CLI tool, which has sub-commands for the various research functions.
The CLI can be used directly from the command line or invoked by agents via Bash commands. Some commands
work on the local filesystem using your own LLM provider keys. Other commands call external APIs hosted by Ai2
For these, the CLI will prompt you to authenticate on first use.

`asta workspace overleaf sync` skips GitHub calls and temporary clones when
Overleaf and the default branch's paper and pairing still match the published
sync record, with no sync branch or held lock. An unverified state uses the
full sync workflow; a refused remote Git probe returns immediately.

`asta workspace overleaf check --project /path/to/scratch-checkout` exercises
co-author import/merge, publication and conflict resolution against an
Overleaf/repository pair reserved for release checks. Run it outside CI
with the pair's existing credentials before adopting a release; see
[scratch release checks](docs/overleaf-sync.md#check-a-release-on-a-scratch-pair).

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

## Giving feedback

These plugins are publicly available, and we appreciate knowing how you use them. Tell your agent to "submit feedback to the Asta team" to let us know!

## Development

See [DEVELOPER.md](DEVELOPER.md) for contributor guidelines, architecture details, and development setup.

## License

Apache 2.0
