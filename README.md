# Asta

Asta is a CLI for scientific literature research, usable by local coding agents.

## Skill Installation

```commandline
# Using skills.sh
npx skills add add allenai/asta-plugins/skills

# In Claude Code
> /plugin marketplace add allenai/asta-plugins
> /plugin install asta-plugins
```

### Available Skills

- **Find Literature** - General paper searching and citation finding
- **Literature Report Generation** - Comprehensive report writing with synthesis
- **Semantic Scholar Lookup** - Quick paper/author lookups and metadata queries
- **Document Management** - Local document metadata index for tracking and searching papers
- **Run Experiment** - Computational experiments with automated report generation

Example user requests that would trigger these skills:
- "Find papers on RLHF"
- "Generate a literature review on transformers"
- "Get details for arXiv:2005.14165"
- "What papers cite the GPT-3 paper?"
- "Store this paper in Asta" / "Search my Asta documents for transformers"
- "Run an experiment to test GPT-4 translation quality"


## CLI Installation

Install the `asta` CLI tool:

```bash
uv tool install git+https://github.com/allenai/asta-plugins.git
```

See `asta --help` for usage instructions.

## Development

See [DEVELOPER.md](DEVELOPER.md) for contributor guidelines, architecture details, and development setup.

## License

Apache 2.0
