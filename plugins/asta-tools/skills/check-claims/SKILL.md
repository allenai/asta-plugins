---
name: check-claims
description: Judge whether factual claims in a research write-up are substantiated — which sentences make checkable claims with no evidence attached, and whether an attached quote actually supports the claim as worded. Use as an author pass before opening a PR on a Quarto/workspace project, and as a review pass over someone else's diff. Triggers on "check my claims", "is this claim supported", "evidence review", "review this draft", or any review of changed `.qmd`/Markdown prose.
allowed-tools: Read Grep Glob Bash(git diff *) Bash(git log *) Bash(git status) Bash(gh pr diff *) Bash(gh pr view *) Bash(make check) Edit
---

# Check claims

Two questions no script can answer: **which sentences assert something checkable and carry no evidence**, and **does the attached quote actually support the claim as written**. Both need reading comprehension, so they live here rather than in the build.

Structural validation is not this skill's job: `make check` already fails on a `.ev` key with no `evidence.yml` entry, an empty quote, an unresolvable `cite`, or an orphaned entry. Run it first — structural breakage reported as a judgement finding wastes a review round. See the `workspace` skill for the evidence machinery (`.ev` spans, `evidence.yml`, `references.bib`).

## Two entry points, one rubric

The rubric below is identical in both passes. That is the point: an author who ran this pass has already answered what the reviewer is about to ask.

- **Author pass** — before opening a PR. Scope is your own change: `git diff origin/main...HEAD -- '*.qmd' '*.md'`. Fix what you find (add evidence, narrow the prose, or drop the claim) rather than reporting it.
- **Review pass** — reviewing a PR. Scope is the PR diff: `gh pr diff <n>`. Report findings; do not silently rewrite someone else's prose.

Judge **changed prose only**. Pre-existing unbacked claims in untouched lines are out of scope for a PR review — note them once, in one line, at most.

## The rubric

For each changed prose sentence, in order:

**1. Does it make a checkable claim?** A claim is checkable if a reader could be wrong about it by reading the source. In practice: a quantity or date; a benchmark/experimental result; a capability, limitation, or finding attributed to a system, model, or paper; a comparative or causal statement ("X outperforms Y", "because Z"); a characterization of what a cited work found or concluded; a statement about field consensus or novelty ("the first", "no prior work").

Not checkable, and not findings: definitions, the project's own framing and argument, statements about artifacts in this repo a reader can open, and explicitly-flagged opinion or open questions.

**2. Is evidence attached?** The claim should sit inside an `.ev` span whose key resolves in `evidence.yml`, or carry a normal citation where the claim *is* that source's headline result. Neither → **unsubstantiated**. Say which part of the sentence is the claim, not just that the sentence is unbacked.

**3. Does the quote support the claim as worded?** Read the quote against the sentence. The recurring failure modes:

| Failure | Looks like |
|---|---|
| Scope drift | Quote is about one dataset/model/setting; prose generalizes to the class. |
| Number mismatch | Prose rounds, converts units, aggregates, or compares against a number the quote doesn't give. |
| Hedge stripped | Quote says "suggests"/"may"/"in our setting"; prose says "shows"/"is". |
| Misattribution | The quote is the cited work *describing someone else's* result, or restating prior work in its intro. |
| Not verbatim | The `quote:` is a paraphrase — it must be copied exactly; your own wording belongs in the prose. |
| Cite mismatch | `cite`/`locator` points somewhere the quote isn't. |
| Stale | A superseded number (leaderboards, model versions, dataset sizes) — check the retrieval date in `provenance:`. |

Verdicts: **supported** / **weak** (quote backs a narrower statement — narrow the prose or find a better quote) / **unsupported** / **unsubstantiated** (no evidence attached at all).

A "weak" verdict is usually fixed by editing the prose down to what the quote says, not by hunting for a stronger quote. Prefer that fix.

## Output

Author pass: fix, then state what changed and anything you deliberately left unbacked and why.

Review pass: one line per finding, worst first, each naming `file:line`, the claim, the verdict, and the concrete fix. No finding without a fix. If nothing is wrong, say the changed claims are backed — do not invent findings to look thorough.

```
docs/methods.qmd:42 — unsupported: "reduces latency by 40%" vs quote giving 40% on the 7B model only.
  Fix: narrow to the 7B setting, or add an evidence entry covering the aggregate.
docs/intro.qmd:11 — unsubstantiated: "the first benchmark to cover wet-lab protocols".
  Fix: add an .ev key with a verbatim quote, or drop "the first".
```

## Getting the evidence you need

When a claim needs backing you don't have, retrieve it rather than softening a real finding: `semantic-scholar` for a specific paper or a snippet search, `find-literature` for a question you need the literature to answer. Then add the `evidence.yml` entry per the `workspace` skill — verbatim `quote`, a `cite` key in `references.bib`, and `provenance:` recording only what you actually observed.
