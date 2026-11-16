# Finding and fetching papers for the CLI

Semantic Scholar's CLI (`s2`) finds the papers, `asta-papers store` fetches their full text into a store, and `theorize papers import` brings the store in. Use this for the first collection and every top-up. Don't mix it with `theorize papers fetch` in the same project: they key papers differently, so every paper would come in twice.

```bash
uv tool install --python 3.13 "git+https://github.com/huggingface/s2-cli@63dba8bc20c959a864b7017444fb8f2faffabd8c"
uv tool install --upgrade --python 3.13 "asta-papers[pymupdf,mistral]>=0.1.0"
command -v s2 asta-papers theorize jq
```

`asta-papers` is its own tool; installing Theorizer doesn't put it on PATH. `s2` reads `S2_API_KEY`. With `MISTRAL_API_KEY` set, `asta-papers` converts PDFs with Mistral; without it, on this machine.

When the person names the papers by Semantic Scholar corpus id and they're the whole corpus, skip the search: `theorize -p <p> papers fetch <corpus ids>` fetches them, and calls no model. Don't add papers with this chain to the same project afterwards.

## Collect, fetch, import

Search with a short query of the plan's key terms, drop repeated DOIs (Semantic Scholar sometimes returns one paper under two ids), and save the list with its query:

```bash
mkdir -p <run>/searches
Q="<the plan's search query>"
s2 search "$Q" --limit 100 --json \
  | jq --arg q "$Q" '.query = $q | .data.data |= (reduce .[] as $p ({seen: {}, out: []};
      (($p.externalIds.DOI // "") | ascii_downcase) as $doi
      | if $doi != "" and .seen[$doi] then . else .seen[$doi] = true | .out += [$p] end) | .out)' \
  > <run>/searches/s1.json
asta-papers store --from-file <run>/searches/s1.json --limit <target> --require-full-text --into <run>/store.json
theorize -p <p> papers import <run>/store.json
```

- `--require-full-text` matters. Without it, a paper with no full text is kept with its abstract as its text, and Theorizer extracts from abstracts too.
- `--into` grows the store in place, keeps the search's order and skips papers already in it, so a rerun resumes.
- Always name the store file. `theorize papers import -` doesn't read stdin: it imports nothing and still exits 0.
- If `s2` fails on a connection error, run it again.

**Top up** until the target is reached: a larger `--limit` on the same list, or another search saved as `s2.json`, `s3.json`. Then import the store again; papers already in the project stay as they are.

**Follow the literature** from a defining paper when it helps:

```bash
s2 refs "<title, DOI, arXiv id or Semantic Scholar id>" --limit 100 --json > <run>/searches/refs1.json
s2 citations "<...>" --limit 100 --json > <run>/searches/cites1.json
asta-papers store --from-file <run>/searches/refs1.json --ids <corpus id>,<corpus id> --require-full-text --into <run>/store.json
```

`asta-papers store` prints its counts last, with the reason for each paper it couldn't get full text for. Check `theorize show papers` for the same title twice: a repeat with one DOI-less id can slip past the filter.
