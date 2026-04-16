---
name: Asta Library
description: Local document metadata index for files used by Asta skills and tools. Use this skill when the user asks to store a document "in Asta" or retrieve "from Asta". Use it when the
  user references an "Asta document" or anything with an `asta://` URI.
allowed-tools:
  - Bash(asta documents *)
  - Read(*)
  - TaskOutput
  - Write(.asta/*)
---

# Asta Documents Management

This skill provides complete document management functionality for tracking research papers, documentation, and resources using the `asta documents` CLI.

**What it does:** Track document metadata (URLs, summaries, tags) in a local index. Think of it as a smart bookmark manager with powerful search capabilities.

**Default Index Location:** `.asta/documents/index.yaml` (relative to current working directory). The `--index-path` flag is optional when using the default location; it's only needed for custom index locations or remote indexes.

## Automatic Indexing of .asta Documents

**IMPORTANT:** When other Asta skills (like literature research) write documents to `.asta/` (in the current working directory), you should automatically index them in the document store. This ensures all Asta-generated documents are tracked and searchable.

**Workflow:**
1. After any Asta skill writes files to `.asta/` (e.g., literature reports, paper collections)
2. Scan the directory for new documents
3. For each document, add it to the index with appropriate metadata:
   - **name**: Extract from filename or document title
   - **url**: Use `file://` URL pointing to the local path (use absolute paths for file:// URLs)
   - **summary**: Extract from document content or use a brief description
   - **tags**: Add relevant tags (e.g., "asta-generated", "literature-report", etc.)
   - **mime-type**: Detect from file extension (e.g., "text/markdown", "application/pdf")

**Example:**
```bash
# After a literature report is written to .asta/literature/report/2024-01-15-ml.md
# Convert relative path to absolute for file:// URL
REPORT_PATH="$(pwd)/.asta/literature/report/2024-01-15-ml.md"
asta documents add "file://${REPORT_PATH}" \
  --name="Literature Report: Machine Learning" \
  --summary="Comprehensive report on machine learning papers from 2023-2024" \
  --tags="asta-generated,literature-report,ml" \
  --mime-type="text/markdown"
```

## Installation

This skill requires the `asta` CLI:

```bash
# Install/reinstall at the correct version
PLUGIN_VERSION=0.12.0
if [ "$(asta --version 2>/dev/null | grep -oE '[0-9]+\.[0-9]+\.[0-9]+')" != "$PLUGIN_VERSION" ]; then
  uv tool install --force git+https://github.com/allenai/asta-plugins.git@v$PLUGIN_VERSION
fi
```

**Prerequisites:** Python 3.11+ and [uv package manager](https://docs.astral.sh/uv/)

## Quick Command Reference

Add `--json` flag to any command for machine-readable output.
Uses `.asta/documents/index.yaml` by default (add `--index-path <file>` for custom locations).

```bash
# List documents
asta documents list
asta documents list --tags="ai,research"

# Search documents (by field)
asta documents search --summary="query"
asta documents search --name="title words"
asta documents search --tags="ai,nlp"
asta documents search --extra=".year > 2020"

# Multi-field search (intersection - matches ALL)
asta documents search --summary="transformers" --tags="ai"

# Multi-field search (union - matches ANY)
asta documents search --summary="transformers" --name="BERT" --union

# Add document (use absolute path for file:// URLs)
asta documents add <url> \
  --name="Title" \
  --summary="Description" \
  --tags="tag1,tag2" \
  --extra='{"author": "Smith et al", "year": 2024, "venue": "NeurIPS"}'

# Get document metadata
asta documents get <uuid>

# Update document
asta documents update <uuid> \
  --name="New Title" \
  --tags="new,tags"

# Fetch document content
asta documents fetch <uuid> -o /tmp/document.pdf

# Manage tags
asta documents add-tags <uuid> --tags="new,tags"
asta documents remove-tags <uuid> --tags="old,tags"

# Cache management
asta documents cache list
asta documents cache stats
asta documents cache clean --days 7

# Summary information (document counts)
asta documents show
```
Always use the command line interface for all operations to ensure proper index management and caching.
Avoid direct read/write operations on the index file.

## Working with Remote Indexes (asta:// URLs)

Asta documents can reference remote indexes using the `asta://` URL scheme. This allows sharing document collections hosted on the web.

**URL Format:**
```
asta://{url-encoded-index-url}/{uuid}
```

Where:
- `{url-encoded-index-url}` is the URL-encoded URL to the remote `index.yaml` file
- `{uuid}` is the 10-character document identifier

**Example:**
```
# Actual index URL: https://example.com/research/index.yaml
# Asta URL: asta://https%3A%2F%2Fexample.com%2Fresearch%2Findex.yaml/6MNxGbWGRC
```

**Workflow:**

When you encounter an `asta://` URL, follow these steps:

1. **Parse the URL** to extract the encoded index URL and document UUID
2. **URL-decode** the index URL
3. **Download the remote index** to a local temporary file
4. **Access documents** using the `--index-path` parameter

**Example:**

```bash
# Given an asta:// URL
ASTA_URL="asta://https%3A%2F%2Fexample.com%2Fresearch%2Findex.yaml/6MNxGbWGRC"

# 1. Parse the URL components (extract encoded index URL and UUID)
ENCODED_INDEX_URL=$(echo "$ASTA_URL" | sed 's|^asta://||' | sed 's|/[^/]*$||')
UUID=$(echo "$ASTA_URL" | sed 's|.*/||')

# 2. URL-decode the index URL
INDEX_URL=$(python3 -c "import urllib.parse; print(urllib.parse.unquote('$ENCODED_INDEX_URL'))")

# 3. Download the remote index
curl -s -o /tmp/remote-index.yaml "$INDEX_URL"

# 4. Get document metadata using --index-path
asta documents get "$UUID" --index-path /tmp/remote-index.yaml

# 5. Fetch document content
asta documents fetch "$UUID" --index-path /tmp/remote-index.yaml -o /tmp/document.pdf
```

**Common Operations with Remote Indexes:**

```bash
# After downloading and decoding the index URL (see examples above)
# Assume TEMP_INDEX points to the downloaded index file

# Search remote index
asta documents search --summary="query" --index-path "$TEMP_INDEX"

# List all documents in remote index
asta documents list --index-path "$TEMP_INDEX"

# Get metadata for specific document
asta documents get "$UUID" --index-path "$TEMP_INDEX"

# Search and fetch from remote index
asta documents search --summary="transformers" --index-path "$TEMP_INDEX" --show-scores
asta documents fetch "$UUID" --index-path "$TEMP_INDEX" -o result.pdf
```

**Important Notes:**

- The `--index-path` parameter works with all read commands (list, search, get, fetch)
- Remote indexes accessed this way are read-only (no add/update/remove operations)
- Downloaded indexes can be cached locally to avoid repeated downloads
- The index URL portion is URL-encoded and must be decoded before use
- The decoded URL supports: http://, https://, file://, s3://, gs://
- Always validate the index file exists and is valid YAML before using it

**Complete Example Workflow:**

```bash
# User provides: asta://https%3A%2F%2Fai.example.org%2Fpapers%2Findex.yaml/AbC123XyZ9

# Step 1: Extract components
ASTA_URL="asta://https%3A%2F%2Fai.example.org%2Fpapers%2Findex.yaml/AbC123XyZ9"
ENCODED_INDEX_URL=$(echo "$ASTA_URL" | sed 's|^asta://||' | sed 's|/[^/]*$||')
UUID=$(echo "$ASTA_URL" | sed 's|.*/||')

# Step 2: URL-decode the index URL
INDEX_URL=$(python3 -c "import urllib.parse; print(urllib.parse.unquote('$ENCODED_INDEX_URL'))")
# Result: https://ai.example.org/papers/index.yaml

# Step 3: Download index to temp location
TEMP_INDEX="/tmp/asta-index-$(date +%s).yaml"
curl -s -o "$TEMP_INDEX" "$INDEX_URL"

# Step 4: Verify download succeeded
if [ ! -f "$TEMP_INDEX" ]; then
    echo "Failed to download index from $INDEX_URL"
    exit 1
fi

# Step 5: Access the document
asta documents get "$UUID" --index-path "$TEMP_INDEX"
asta documents fetch "$UUID" --index-path "$TEMP_INDEX" -o /tmp/paper.pdf

# Step 6: Read the content
# Read(/tmp/paper.pdf)
```

## Fetch Document Content

The index stores metadata only. The content of a document is retrievable via its URL. The `fetch` command retrieves the content and caches it locally for future use.

**Fetch to file (with automatic caching):**
```bash
asta documents fetch <uuid> -o /tmp/document.pdf
```

### Supported URL Protocols

The system supports multiple protocols for document URLs:

**Local and Web:**
- `http://` and `https://` - Web URLs (uses curl)
- `file://` - Local file system (uses curl)

**Cloud Storage:**
- `s3://` - Amazon S3 (requires AWS CLI)
- `gs://` - Google Cloud Storage (requires gsutil)

**Cloud Storage Setup:**

For S3:
```bash
# Install AWS CLI
brew install awscli  # macOS
pip install awscli   # or via pip

# Configure credentials
aws configure
# Or use: AWS_ACCESS_KEY_ID, AWS_SECRET_ACCESS_KEY, AWS_PROFILE
```

For GCS:
```bash
# Install Google Cloud SDK
brew install --cask google-cloud-sdk  # macOS

# Authenticate
gcloud auth login
# Or use: GOOGLE_APPLICATION_CREDENTIALS=/path/to/service-account.json
```

**Examples:**
```bash
# Add document from S3
asta documents add s3://my-bucket/papers/research.pdf \
  --name="Research Paper" \
  --summary="ML research findings" \
  --tags="ml,research"

# Add document from GCS
asta documents add gs://my-bucket/docs/spec.pdf \
  --name="Technical Spec" \
  --summary="System specifications" \
  --tags="docs"

# Fetch works the same for all protocols
asta documents fetch <uuid> -o local-copy.pdf
```

### Cache Management

**List cached items:**
```bash
asta documents cache list
```

**Show cache statistics:**
```bash
asta documents cache stats
```

**Clean old cache entries:**
```bash
# Remove items older than N days
asta documents cache clean --days 14
```

**Clear entire cache:**
```bash
asta documents cache clear
asta documents cache clear -y  # Skip confirmation
```

**Show specific item details:**
```bash
asta documents cache info <hash>
```

## Common Workflows

### Workflow 1: Index Asta-Generated Documents

```bash
# After literature find writes to .asta/
# List all files in .asta/
ls -la .asta/

# For each new document, add to index (convert to absolute path for file:// URL)
REPORT_PATH="$(pwd)/.asta/literature/report/literature-report.md"
asta documents add "file://${REPORT_PATH}" \
  --name="Literature Report: Transformers" \
  --summary="Research findings on transformer architectures" \
  --tags="asta-generated,literature-report,transformers" \
  --mime-type="text/markdown"

# Now the document is searchable
asta documents search --tags="asta-generated"
```

### Workflow 2: Add and Organize Papers

```bash
# Add research paper
asta documents add https://arxiv.org/pdf/1706.03762.pdf \
  --name="Attention Is All You Need" \
  --summary="Seminal paper introducing Transformer architecture" \
  --tags="ai,research,nlp,transformers" \
  --mime-type="application/pdf" \
  --extra='{"author": "Vaswani et al", "year": 2017, "venue": "NeurIPS"}'

# Search papers by tag
asta documents search --tags="transformers"
```

### Workflow 3: Search and Fetch

```bash
# Search for relevant documents
asta documents search --summary="transformer architecture" --show-scores

# Get metadata for top result (using UUID from search results)
asta documents get 6MNxGbWGRC

# Fetch content
asta documents fetch 6MNxGbWGRC -o /tmp/paper.pdf -q

# Read with PDF support
# Read(/tmp/paper.pdf)
```

### Workflow 4: Search with JSON Processing

```bash
# Search and extract UUIDs
RESULTS=$(asta documents search --summary="query" --json)

# Get first UUID (example with Python)
UUID=$(echo "$RESULTS" | python3 -c "import sys,json; results=json.load(sys.stdin); print(results[0]['result']['uuid'] if results else '')")

# Fetch that document
asta documents fetch "$UUID" -o result.pdf
```

### Workflow 5: Bulk Tag Management

```bash
# List documents with old tag
DOCS=$(asta documents list --tags="old-tag" --json)

# For each, remove old tag and add new
for uuid in $(echo "$DOCS" | python3 -c "import sys,json; print('\\n'.join([d['uuid'] for d in json.load(sys.stdin)]))"); do
    asta documents remove-tags "$uuid" --tags="old-tag"
    asta documents add-tags "$uuid" --tags="new-tag"
done
```

### Workflow 6: Update Multiple Fields

```bash
# Get current metadata (using UUID)
asta documents get 6MNxGbWGRC

# Update multiple fields
asta documents update 6MNxGbWGRC \
  --name="Updated Title" \
  --summary="Updated summary with more details" \
  --tags="updated,revised,2025"
```

### Workflow 7: Cache Maintenance

```bash
# Check cache usage
asta documents cache stats

# List what's cached
asta documents cache list

# Remove old entries if cache is large
asta documents cache clean --days 7

# Verify cache reduction
asta documents cache stats
```

## Field-Specific Search

Asta uses different search strategies optimized for each document field. You can search single fields or combine multiple fields with intersection/union modes.

### Single Field Search

**--summary** (Summary search):
- Uses best available method automatically:
  - Hybrid (BM25 + semantic embeddings) → best quality
  - BM25 (keyword relevance ranking) → fast indexed
  - FTS5 (full-text search) → fallback
  - Simple (substring matching) → always available
- Optimized for natural language queries
- Understands semantic meaning
- Produces relevance scores for ranking
- Example: `asta documents search --summary="papers about transformers"`

**--name** (Name search):
- Simple case-insensitive word matching
- Splits query into words, matches any word in name
- Score = (matched words / total query words)
- Fast, no indexing needed
- Produces match scores for ranking
- Example: `asta documents search --name="Attention"`

**--tags** (Tag search):
- Comma-separated tag matching
- Case-insensitive
- Acts as a filter (no meaningful relevance scores)
- Finds documents with any matching tags
- Example: `asta documents search --tags="ai,nlp"`

**--extra** (Extra metadata search):
- JSONPath-like query syntax
- Supported operators: `>`, `>=`, `<`, `<=`, `==`, `contains`
- Numeric and string comparisons
- Acts as a filter (no meaningful relevance scores)
- Examples:
  - `asta documents search --extra=".year > 2020"`
  - `asta documents search --extra=".author contains Smith"`
  - `asta documents search --extra=".venue == NeurIPS"`

### Multi-Field Search

Combine multiple field queries to create powerful filtered searches:

**Intersection mode (default)**:
- Returns documents matching ALL specified field queries
- Example: `asta documents search --summary="transformers" --tags="ai"`
- Only returns documents where summary contains "transformers" AND tags include "ai"

**Union mode (`--union` flag)**:
- Returns documents matching ANY specified field query
- Example: `asta documents search --summary="transformers" --name="BERT" --union`
- Returns documents where summary contains "transformers" OR name contains "BERT"

**Hierarchical Scoring**:

Results are sorted using a priority hierarchy where tags/extra act as filters:

1. **Summary score** (highest priority) - if `--summary` present
   - Uses semantic/hybrid search relevance
   - Best for natural language queries

2. **Name score** (medium priority) - if `--name` present
   - Uses word-matching score
   - Used when no summary query

3. **Created timestamp** (lowest priority) - if only `--tags` or `--extra`
   - Sorts by creation time (newest first)
   - Only used when no summary/name queries

**Examples**:
```bash
# Summary + tags: Sorted by summary relevance (tags filter)
asta documents search --summary="machine learning" --tags="ai"

# Name + tags: Sorted by name word-match (tags filter)
asta documents search --name="Python" --tags="programming"

# Tags only: Sorted by creation timestamp
asta documents search --tags="research"

# Three fields: Summary ranks, name and extra filter
asta documents search --summary="transformers" --name="Attention" --extra=".year > 2015"
```

## Output Formats

**Human-readable (default):**
- Formatted tables and lists
- Color-coded (if terminal supports)
- Progress messages

**JSON (`--json` flag):**
- Machine-readable
- All fields included
- For scripting and integration

**Verbose (`-v` flag for list):**
- Shows all metadata fields
- Includes extra metadata
- Full URIs and timestamps

## Best Practices

1. **Auto-index Asta documents**: Always index documents written to `.asta/` by other skills (uses `.asta/documents/index.yaml` by default)
2. **Use descriptive summaries**: They're indexed for search
3. **Tag consistently**: Establish a tagging scheme (e.g., "asta-generated" for auto-indexed docs)
4. **Use extra metadata**: Store author, year, venue for papers
5. **Let fetch handle caching**: Don't manually check cache
6. **Use JSON for scripting**: More reliable than parsing text
7. **Use quiet mode in scripts**: `-q` suppresses progress messages
8. **Use absolute paths for file:// URLs**: Convert relative paths with `$(pwd)/` to ensure correct resolution

## Troubleshooting

**"asta-documents: command not found"**
- The command should auto-install on first use
- Verify installation: `uv tool list | grep asta`
- Add to PATH: `export PATH="$HOME/.local/bin:$PATH"`
- Manual install: `uv tool install git+https://github.com/allenai/asta-resource-repo.git`

**"Document not found"**
- Verify UUID: `asta documents list --json | grep <partial-uuid>`
- Check namespace: UUIDs are namespace-specific
- Ensure there is an index file at `.asta/documents/index.yaml`

**"Fetch failed"**
- Check URL is accessible: `curl -I <url>`
- Try force refresh: `--force`
- Check network connection

**"Search returns no results"**
- Try simpler query terms
- Search by name or tags for exact matching:
  - `asta documents search --name="keyword"`
  - `asta documents search --tags="tag"`
- Check if documents exist: `asta documents list`
- Try union mode if using multiple fields: `--union`

**"Cache is large"**
- Check size: `asta documents cache stats`
- Clean old entries: `asta documents cache clean --days 7`
- Clear if needed: `asta documents cache clear -y`

## Updating

**Update the asta-documents CLI:**
```bash
uv tool install --reinstall git+https://github.com/allenai/asta-resource-repo.git
```

## Links

- **Repository**: https://github.com/allenai/asta-resource-repo
- **Documentation**: https://github.com/allenai/asta-resource-repo/blob/main/README.md
- **Issues**: https://github.com/allenai/asta-resource-repo/issues
