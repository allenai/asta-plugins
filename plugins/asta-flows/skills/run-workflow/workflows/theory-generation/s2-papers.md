# S2 to asta-papers to Theorizer

How theory generation finds and fetches its papers: the Semantic Scholar CLI (`s2`) collects
them, `asta-papers store` fetches their full text into a paper store, and Theorizer imports that
store. Use this chain for the first collection and for every top-up. Do not use
`theorize papers search` or `theorize papers fetch` in this workflow: they key papers
differently, so mixing them with this chain puts every paper in the project twice.

## Setup

```bash
uv tool install --python 3.13 "git+https://github.com/huggingface/s2-cli@63dba8bc20c959a864b7017444fb8f2faffabd8c"
uv tool install --upgrade --python 3.13 "asta-papers[pymupdf,mistral]>=0.1.0"
command -v s2 asta-papers theorize jq
```

`asta-papers` is its own tool: installing Theorizer does not put it on PATH. `s2` reads
`S2_API_KEY`. With `MISTRAL_API_KEY` set, `asta-papers` converts PDFs with Mistral OCR;
without it, locally. Unpaywall is not used: asta-papers 0.1.0 has no Unpaywall route.

## Steps

`<run>` is the run's directory and `<run>/theory` its Theorizer project, as in
[Theory generation](README.md).

1. **Collect and fetch.** Search with a short query of the plan's key terms, drop repeat DOIs
   (Semantic Scholar sometimes returns one paper under two ids), save that list with its query
   (the run's pages show it), and let `asta-papers store` fetch full text for the first
   `<target>` papers on it into the store:

   ```bash
   mkdir -p <run>/searches
   Q="<the plan's search query>"
   s2 search "$Q" --limit 100 --json \
     | jq --arg q "$Q" '.query = $q | .data.data |= (reduce .[] as $p ({seen: {}, out: []};
         (($p.externalIds.DOI // "") | ascii_downcase) as $doi
         | if $doi != "" and .seen[$doi] then . else .seen[$doi] = true | .out += [$p] end) | .out)' \
     > <run>/searches/s1.json
   asta-papers store --from-file <run>/searches/s1.json --limit <target> --require-full-text --into <run>/store.json
   ```

   `--into` grows the store in place: it is saved as it goes, papers already in it are
   skipped, and the search's rank order is kept, so a rerun resumes. `--require-full-text`
   matters: without it, a paper without full text is kept with its abstract as its text, and
   Theorizer would extract from abstracts. If `s2` fails on a connection error, run it again.

2. **Follow the literature** from a defining paper when it helps, and fetch the ones you pick:

   ```bash
   s2 refs "<title, DOI, arXiv id or Semantic Scholar id>" --limit 100 --json > <run>/searches/refs1.json
   s2 citations "<title, DOI, arXiv id or Semantic Scholar id>" --limit 100 --json > <run>/searches/cites1.json
   asta-papers store --from-file <run>/searches/refs1.json --ids <corpus id>,<corpus id> --require-full-text --into <run>/store.json
   ```

3. **Top up** until the target is reached: take more of the same de-duplicated list (papers
   already in the store are skipped), or search again from another angle, saved the same way as
   `s2.json`, `s3.json`:

   ```bash
   asta-papers store --from-file <run>/searches/s1.json --limit <a larger N> --require-full-text --into <run>/store.json
   ```

4. **Into Theorizer.** Import the store as a file. A store piped into `theorize papers import`
   on stdin is read as one paper, so always name the `.json` file:

   ```bash
   theorize -p <run>/theory papers import <run>/store.json   # merged as is: no re-fetch, no LLM call
   theorize -p <run>/theory show papers
   ```

   The person's own papers go into the same project with `theorize -p <run>/theory papers import
   <their folder>` ([Bring Your Own Papers](README.md#bring-your-own-papers)). After a top-up,
   import the store again; papers already in the project are kept as they are.

5. **References.** `theorizer-site-data --bib references.bib` adds a BibTeX entry for each
   of the run's papers to the site's `references.bib`, keyed `s2-<corpus id>`
   ([The run's page](README.md#the-runs-page)). It takes a paper's authors, venue and DOI from
   the store entry's own record where asta-papers wrote one, and from Semantic Scholar's
   (`s2_metadata`) otherwise.

`asta-papers store` prints its counts last, and the reason for each paper it could not fetch
full text for. Report how many papers were tried, how many have full text, and why the others do
not. Check `show papers` for the same title twice; a repeat that slipped past the DOI filter
(one id with a DOI, one without) is worth noting.
