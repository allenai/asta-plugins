---
name: check-claims
description: Judge whether factual claims in an evidence-backed research write-up are substantiated — which claims assert something checkable with no evidence attached, and whether an attached quote supports the claim as worded. Works over whatever scope the request names — a pull request diff, your own uncommitted change, one file, or a whole project audited end to end. Triggers on "check my claims", "is this claim supported", "evidence review", "audit the evidence", or review of research prose using `.ev` evidence.
allowed-tools: Read Grep Glob Bash(git diff *) Bash(git status) Bash(gh pr diff *) Bash(gh pr view *) Edit Skill(asta-tools:semantic-scholar) Skill(asta-tools:find-literature) Skill(asta-tools:workspace)
---

# Check claims

Covers only what needs reading: is a claim backed, and does its quote say what the prose says. Structural validation — unresolved `.ev` keys, empty quotes, unresolvable citations, orphaned entries — belongs to the project's `make check`; don't redo it here, and don't assume it ran unless CI or the project's docs say so. See `workspace` for the evidence machinery (`.ev` spans, `evidence.yml`, `references.bib`).

## Procedure

1. **Read what the request scopes.** A change under review: `gh pr diff <n>`. Your own change: `git diff` and `git status`, covering committed, staged and unstaged. A file or a whole project: read it one file at a time. No scope named → the change in hand; don't widen it unasked.
2. **For a change, the scope is wider than the changed prose.** A changed `evidence.yml` or `references.bib` entry changes what unchanged prose asserts, so also read the spans citing it: `grep -rn 'key="<key>"' docs/`.
3. **Judge each sentence: does it assert something a source could confirm or refute?** Yes for a quantity or date, a benchmark result, a capability or limitation attributed to a system or paper, a comparison or causal claim, a characterization of what a cited work found, a novelty claim ("the first", "no prior work"). No for definitions, the write-up's own framing and argument, pointers to files in this repo, and flagged opinion or open questions.
4. **If yes, is evidence attached?** An `.ev` span whose key resolves in `evidence.yml`, or a plain citation where the claim *is* that source's headline result. Neither → `unsubstantiated`; name the clause that is the claim, not the whole sentence.
5. **If a quote is attached, read it against the highlighted span.** The span must not claim more than the quote does — in scope, in number, or in certainty. `supported` / `weak` / `unsupported`. A `weak` verdict is usually fixed by editing the prose down to the quote, not by hunting a stronger one.
6. **Author: fix. Reviewer: report.** Judge each sentence as you reach it; don't build a claim inventory first. Carry one thing across the pass: which `evidence.yml` keys you have already judged — several spans can cite one key, so a bad quote is one finding naming the spans it affects, not one finding per span. Each finding needs where it is, the claim, the verdict, and the fix; no finding without a fix. Nothing wrong: say what you covered and that its claims are backed; don't invent findings to look thorough.

## Author and reviewer differ in two ways

- **Authors fix; reviewers report.** Reviewing someone else's change, don't edit their files or run their code — read-only inspection and existing CI results.
- **Authors may retrieve; reviewers may not.** Needing a quote you don't have, load `semantic-scholar` (specific paper or snippet) or `find-literature` (a question), then add the entry per `workspace`: `quote` pasted verbatim from the source, `cite` a `references.bib` key, `provenance` recording only the retrieval you actually ran. Reviewing, recommend the evidence or wording instead.
