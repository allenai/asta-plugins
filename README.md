# Asta

Asta is a CLI for scientific literature research, usable by local coding agents.

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
- **Run Experiment** - Computational experiments with automated report generation
- **PDF Text Extraction** - Extract text from PDFs using olmOCR API (no GPU required)

Example user requests that would trigger these skills:
- "Find papers on RLHF"
- "Generate a literature review on transformers"
- "Get details for arXiv:2005.14165"
- "What papers cite the GPT-3 paper?"
- "Store this paper in Asta" / "Search my Asta documents for transformers"
- "Run an experiment to test GPT-4 translation quality"
- "Extract text from this PDF" / "OCR this document"


## CLI Installation

Install the `asta` CLI tool:

```bash
uv tool install git+https://github.com/allenai/asta-plugins.git
```

To upgrade:

```bash
uv tool upgrade asta
```

See `asta --help` for usage instructions.

### PDF Text Extraction (olmOCR)

Extract high-quality text from PDFs using the olmOCR tool. Supports both cloud API providers (no GPU required) and local GPU inference.

**Quick Start (API Mode):**

1. Choose an API provider and get an API key:
   - **Cirrascale** (recommended): $0.07/1M tokens - AI2 partner, cheapest option
   - **DeepInfra**: $0.09/1M tokens - Easy signup at [deepinfra.com](https://deepinfra.com)
   - **Parasail**: $0.10/1M tokens - Enterprise support at [parasail.io](https://parasail.io)

2. Extract text from a PDF:
   ```bash
   # olmocr will auto-install on first use
   export DEEPINFRA_API_KEY='your-api-key-here'

   asta ocr ~/workspace/output \
     --pdfs document.pdf \
     --server https://api.deepinfra.com/v1/openai \
     --api_key "$DEEPINFRA_API_KEY" \
     --markdown

   # Output: ~/workspace/output/markdown/document.md
   ```

**Cost**: ~$0.001-0.01 per typical PDF (10-50 pages)

**Features**:
- Works with scanned documents and complex layouts
- Preserves tables, equations, and formatting
- Fast (~10-20 seconds per page with cloud API)
- Supports batch processing with parallel workers

See `asta ocr --help` for all options and the skill documentation for detailed examples.

## Development

See [DEVELOPER.md](DEVELOPER.md) for contributor guidelines, architecture details, and development setup.

## License

Apache 2.0
