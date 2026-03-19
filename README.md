# Asta

Asta is a set of skills for scientific research, usable by local coding agents.

## Skill Installation

```commandline
# Using skills.sh
npx skills add add allenai/asta-plugins/skills

# In Claude Code
> /plugin marketplace add allenai/asta-plugins
> /plugin install asta
```

### Available Skills

- **Find Literature** - General paper searching and citation finding
- **Literature Report Generation** - Comprehensive report writing with synthesis
- **Semantic Scholar Lookup** - Quick paper/author lookups and metadata queries
- **Document Management** - Local document metadata index for tracking and searching papers
- **PDF Text Extraction** - Extract text from PDFs using olmOCR (cloud-based, no GPU required)
- **Run Experiment** - Computational experiments with automated report generation

Example user requests that would trigger these skills:
- "Find papers on RLHF"
- "Generate a literature review on transformers"
- "Get details for arXiv:2005.14165"
- "What papers cite the GPT-3 paper?"
- "Store this paper in Asta" / "Search my Asta documents for transformers"
- "Extract text from this PDF" / "Convert PDF to markdown"
- "Run an experiment to test GPT-4 translation quality"
- "Extract text from this PDF" / "OCR this document"


## Implementation

The skills install an `asta` CLI tool, which has sub-commands for the various research functions. 
The CLI can be used directly from the command line or invoked by agents via Bash commands.

Some skills are pass-through commands to CLIs hosted in other repos. These are installed automatically
on first invocation.

Some skills are implemented by calling external APIs hosted by Ai2. For these, the CLI will prompt you to authenticate on first use.

## Development

See [DEVELOPER.md](DEVELOPER.md) for contributor guidelines, architecture details, and development setup.

## License

Apache 2.0
