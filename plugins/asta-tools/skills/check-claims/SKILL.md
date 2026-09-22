---
name: check-claims
description: Judge whether factual claims in a research write-up are substantiated — which sentences make checkable claims with no evidence attached, and whether an attached quote actually supports the claim as worded. Use as an author pass before opening a PR on a Quarto/workspace project, and as a review pass over someone else's diff. Triggers on "check my claims", "is this claim supported", "evidence review", "review this draft", or any review of changed `.qmd`/Markdown prose.
allowed-tools: Read Grep Glob Bash(git diff *) Bash(git log *) Bash(git status) Bash(git symbolic-ref *) Bash(git merge-base *) Bash(gh repo view *) Bash(gh pr diff *) Bash(gh pr view *) Edit Skill(asta-tools:semantic-scholar) Skill(asta-tools:find-literature) Skill(asta-tools:workspace)
---

# Check claims

Two questions no script can answer: **which sentences assert something checkable and carry no evidence**, and **does the attached quote actually support the claim as written**. Both need reading comprehension, so they live here rather than in the build.

Structural validation is not this skill's job. Deterministic tooling should catch unresolved `.ev` keys, empty quotes, unresolvable citations, and orphaned entries; this skill supplies the judgement that tooling cannot. Do not assume a project's `make check` includes those validations unless its trusted documentation or CI says so. See the `workspace` skill for the evidence machinery (`.ev` spans, `evidence.yml`, `references.bib`).

## Scope

Inspect the requested diff. For your own change, fix findings before reporting the result. When reviewing someone else's change, report findings without editing the change or running its code; use read-only inspection and existing CI results.

Judge changed prose, plus every changed `evidence.yml` entry and every claim that references it. A changed bibliography entry also brings into scope the evidence entries that cite it and the claims that reference those entries. Use read-only search to follow those links even when the affected claim itself is on an unchanged line. Pre-existing unbacked claims unrelated to a changed evidence or bibliography entry remain out of scope for a PR review — note them once, in one line, at most.

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

## Getting the evidence you need (author pass only)

During an author pass, when a claim needs backing you don't have, retrieve it rather than softening a real finding: load `semantic-scholar` for a specific paper or snippet search, or `find-literature` for a question you need the literature to answer. Then load `workspace` and add the `evidence.yml` entry per its evidence instructions — verbatim `quote`, a `cite` key in `references.bib`, and `provenance:` recording only what you actually observed.

During a review pass, do not retrieve new evidence or edit the author's files. Report the gap and recommend the specific evidence or wording change the author should supply.
