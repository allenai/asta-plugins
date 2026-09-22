---
name: check-claims
description: Judge whether factual claims in a research write-up are substantiated — which changed sentences assert something checkable with no evidence attached, and whether an attached quote supports the claim as worded. Run as an author pass over your own diff before opening a PR on a Quarto/workspace project, and as a review pass over someone else's. Triggers on "check my claims", "is this claim supported", "evidence review", or any review of changed `.qmd`/Markdown prose.
allowed-tools: Read Grep Glob Bash(git diff *) Bash(git log *) Bash(git status) Bash(git symbolic-ref *) Bash(git merge-base *) Bash(gh repo view *) Bash(gh pr diff *) Bash(gh pr view *) Edit Skill(asta-tools:semantic-scholar) Skill(asta-tools:find-literature) Skill(asta-tools:workspace)
---

# Check claims

Covers only what needs reading: is a changed claim backed, and does its quote say what the prose says. Structural validation — unresolved `.ev` keys, empty quotes, unresolvable citations, orphaned entries — belongs to the project's `make check`; don't redo it here, and don't assume it ran unless CI or the project's docs say so. See `workspace` for the evidence machinery (`.ev` spans, `evidence.yml`, `references.bib`).

## Procedure

1. **Get the diff.** Own branch: `git diff $(git merge-base HEAD origin/main)...HEAD -- '*.qmd' '*.md' '*evidence.yml' '*.bib'`. Someone else's: `gh pr diff <n>`.
2. **Set scope.** Changed prose; every changed `evidence.yml` entry plus the claims referencing it (`grep -rn 'key="<key>"' docs/`); a changed `.bib` entry pulls in the evidence entries citing it. Pre-existing unbacked claims elsewhere are out of scope — note them once, in one line.
3. **Per changed sentence, ask: could a reader be wrong about this by reading the source?** Yes for a quantity or date, a benchmark result, a capability or limitation attributed to a system or paper, a comparison or causal claim, a characterization of what a cited work found, a novelty claim ("the first", "no prior work"). No for definitions, the write-up's own framing and argument, pointers to files in this repo, and flagged opinion or open questions.
4. **If yes, is evidence attached?** An `.ev` span whose key resolves in `evidence.yml`, or a plain citation where the claim *is* that source's headline result. Neither → `unsubstantiated`; name the clause that is the claim, not the whole sentence.
5. **If a quote is attached, read it against the highlighted span.** The span must not claim more than the quote does — in scope, in number, or in certainty. `supported` / `weak` / `unsupported`.
6. **Author: fix. Reviewer: report.** A `weak` verdict is usually fixed by editing the prose down to the quote, not by hunting a stronger one.

## Step 5, worked

Prose (`docs/reference-research-agents.qmd`), the bracketed part being the span the reader hovers:

```
autonomous cycles [recapitulate peer-reviewed publications without major
errors ~80–90% of the time]{.ev key="data-to-paper-accuracy"} for simple goals
```

Quote behind that key:

> "For simple research goals, a fully-autonomous cycle can create manuscripts which recapitulate peer-reviewed publications without major errors in about 80-90%, yet as goal complexity increases, human co-piloting becomes critical for assuring accuracy."

`weak`. The quote is conditional on simple goals; the span stops before "for simple goals", so what the reader hovers reads unconditional. Fix: move the span's closing brace past "for simple goals". Note what this costs to catch — every key resolves, the quote is verbatim, the cite is good, so the mechanical check passes both before and after.

## Output

Review pass — one line per finding, worst first, `file:line` + the claim + verdict + the fix. No finding without a fix. Nothing wrong: say the changed claims are backed; do not invent findings to look thorough.

```
docs/methods.qmd:42 — unsupported: "reduces latency by 40%"; quote gives 40% on the 7B model only.
  Fix: narrow to the 7B setting, or add an evidence entry covering the aggregate.
docs/intro.qmd:11 — unsubstantiated: "the first benchmark to cover wet-lab protocols".
  Fix: add an .ev key with a verbatim quote, or drop "the first".
```

Author pass — apply the fixes, then state what changed and anything you left unbacked deliberately.

## Author and reviewer differ in two ways

- **Authors fix; reviewers report.** Reviewing someone else's change, don't edit their files or run their code — read-only inspection and existing CI results.
- **Authors may retrieve; reviewers may not.** Needing a quote you don't have, load `semantic-scholar` (specific paper or snippet) or `find-literature` (a question), then add the entry per `workspace`: `quote` pasted verbatim from the source, `cite` a `references.bib` key, `provenance` recording only the retrieval you actually ran. Reviewing, recommend the evidence or wording instead.
