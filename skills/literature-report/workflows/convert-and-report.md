# Convert External Papers to Find-Literature Format

Use when the user has papers in a non-standard form — titles, DOIs, arXiv IDs, URLs, a BibTeX file, CSV, or any other format — and wants a literature report from them.

<process>

## Step 1: Identify the papers

Determine what the user has provided. Common forms:
- A list of paper titles
- DOIs or arXiv IDs
- Semantic Scholar corpus IDs or URLs
- A `.bib` file
- A CSV or spreadsheet
- Inline references in a document

## Step 2: Resolve each paper via Semantic Scholar

For each paper, look it up to get full metadata:

```bash
# By arXiv ID
asta papers get ARXIV:2005.14165 --fields title,abstract,year,authors,venue,citationCount,corpusId

# By DOI
asta papers get DOI:10.1234/example --fields title,abstract,year,authors,venue,citationCount,corpusId

# By corpus ID
asta papers get CorpusId:12345 --fields title,abstract,year,authors,venue,citationCount,corpusId

# By title search (when only title is available)
asta papers search "exact paper title" --limit 5 --fields title,abstract,year,authors,venue,citationCount,corpusId
```

For title searches, verify the match is correct by checking authors and year.

## Step 3: Build the results JSON

Construct a `LiteratureSearchResult` JSON file matching the find-literature schema:

```json
{
  "query": "<user's research topic or description>",
  "results": [
    {
      "corpus_id": 12345,
      "title": "Paper Title",
      "abstract": "...",
      "year": 2023,
      "authors": [{"name": "Author Name", "authorId": "123"}],
      "venue": "Conference Name",
      "citation_count": 50,
      "relevance_score": 0.9,
      "relevance_judgement": {
        "relevance": 9,
        "relevanceSummary": "Brief explanation of why this paper is relevant",
        "relevanceCriteriaJudgements": []
      },
      "snippets": [],
      "citation_contexts": []
    }
  ]
}
```

Key points:
- Set `relevance_score` between 0 and 1 based on your judgement of relevance to the user's topic. If no clear ranking, use 0.8 for all.
- The `query` field should describe the research topic, not just repeat the user's input.
- `snippets` and `citation_contexts` will be empty since we don't have full-text access — this is fine, the report will rely on abstracts.

Save to: `.asta/literature/find/YYYY-MM-DD-topic-slug.json`

## Step 4: Generate the report

Now follow `workflows/generate-report.md` using the converted results file.

</process>

<note>
If the user has a large collection (20+ papers), consider whether `asta literature find` with a well-crafted query would produce better results than manual conversion — it provides relevance scores, snippets, and citation contexts that improve report quality.
</note>
