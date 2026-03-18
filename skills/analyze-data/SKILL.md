---
name: Asta Data Analysis
description: Analyze data using DataVoyager AI agent. Use when the user asks to "analyze data", "explore dataset", "visualize data", "run data analysis", or needs help with data science tasks.
allowed-tools:
  - Bash(asta analyze-data *)
  - Bash(mkdir -p .asta/analyze-data/*)
  - Read(.asta/analyze-data/*)
  - TaskOutput
---

# Analyze Data with DataVoyager

Analyze datasets using the DataVoyager AI agent. This skill provides an interactive AI-powered data analysis environment that can explore datasets, create visualizations, and perform statistical analysis.

## Installation

If `asta` command is not available, install it using `uv tool install git+ssh://git@github.com/allenai/asta-plugins.git`

**Prerequisites:** Python 3.11+ and [uv package manager](https://docs.astral.sh/uv/)

Verify installation with `asta analyze-data --help`

## Workflow

The user will typically:
1. Provide a dataset file path or ask to analyze data
2. Describe the analysis they want to perform
3. Request visualizations or statistical summaries

### Default Output Locations

**IMPORTANT**: Always specify output locations to keep analyses organized in `.asta/analyze-data/`:

- **OUTPUTS_DIR**: `.asta/analyze-data/<YYYY-MM-DD-slug>/` where:
  - `YYYY-MM-DD` is the current date
  - `slug` is a short descriptive name derived from the analysis task (e.g., "sales-analysis", "customer-segmentation")

**Example directory structure:**
```
.asta/analyze-data/
├── 2024-01-15-sales-analysis/
│   ├── plots/
│   └── [analysis outputs]
└── 2024-01-16-customer-segmentation/
    ├── plots/
    └── [analysis outputs]
```

### Running DataVoyager

DataVoyager runs in interactive mode by default. The basic command is:

```bash
# Run DataVoyager with default Docker backend (recommended)
asta analyze-data
```

**Backend Options:**
- `--backend docker` (default): Local Docker container for isolated execution
- `--backend modal`: Remote serverless execution

**Configuration:**
- `--config path/to/config.yaml`: Use custom configuration
- `--log-level INFO`: Set logging level (DEBUG, INFO, WARNING, ERROR)

### Example Usage

**Basic interactive analysis:**
```bash
# Start DataVoyager in interactive mode
asta analyze-data

# With specific backend
asta analyze-data --backend docker

# With custom config
asta analyze-data --config .asta/analyze-data/config.yaml
```

**Creating organized output directories:**
```bash
# Create output directory with date and slug
OUTPUTS_DIR=".asta/analyze-data/$(date +%Y-%m-%d)-sales-analysis"
mkdir -p "$OUTPUTS_DIR"

# Run DataVoyager (outputs will be saved by the agent)
cd "$OUTPUTS_DIR"
asta analyze-data
```

### Notes

- **Output Directory**: Create `.asta/analyze-data/<YYYY-MM-DD-slug>/` directory before running analysis
- **Task Slug**: Create a short descriptive slug from the analysis task (e.g., "sales-analysis", "data-exploration"). Keep it lowercase with hyphens.
- **Docker Backend**: Recommended for safe, isolated code execution. Requires Docker to be installed and running.
- **Modal Backend**: Serverless execution option for remote computation
- **Interactive Mode**: The agent will prompt you for dataset paths and analysis instructions
- Always inform the user where outputs were saved after analysis completes
