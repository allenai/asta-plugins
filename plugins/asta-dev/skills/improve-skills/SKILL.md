---
name: improve-skills
description: Report or fix a behavior gap in Asta skills. Use when an agent does the wrong thing, doesn't do what was asked, or lacks a capability that's wanted.
allowed-tools: Bash(git clone *) Bash(git fetch *) Bash(git worktree *) Bash(git checkout *) Bash(git add *) Bash(git commit *) Bash(git tag *) Bash(gh issue view *) Bash(jq *) Bash(eval_env *) Bash(asta auth print-token *) Read Write Edit
---

# Improve Asta skills

## 1. Capture the issue (bug or feature idea)

Write the gap to `<project-root>/.asta/improve-skills/<slug>.md` (absolute path, dated slug): the skill(s), prompt, current vs. desired behavior, and relevant setup state. Seed it from an existing issue/doc/thread if one exists (`gh issue view <num> --repo allenai/asta-plugins --json body --jq .body > <project-root>/.asta/improve-skills/<slug>.md`).

> **If stopping here (report):** file it as a new issue (skip if it already is one): `gh issue create --repo allenai/asta-plugins --title "<summary>" --body-file <project-root>/.asta/improve-skills/<slug>.md`.

## 2. Assemble the case set

Set a dev root for the repos, then add or reuse cases in the `asta_skills` suite (under `$DEV_ROOT/asta-bench-private`):

```bash
export DEV_ROOT=<your dev dir>
[ -d "$DEV_ROOT/asta-bench-private" ] || git clone git@github.com:allenai/asta-bench-private "$DEV_ROOT/asta-bench-private"
```

Two groups:

- **Cases for the behavior** (skip if regression-checking only). Reuse existing cases that fit; otherwise add new entries on a branch in `asta-bench-private` (see the [`asta_skills` eval README](https://github.com/allenai/asta-bench-private/blob/main/astabench/ai2/evals/asta_skills/README.md) for case format and metric handlers).
- **Regression guards.** Existing cases that could be affected. Start by searching the suite's `data.json` for cases referencing the changed skill(s), but use judgment — cross-skill effects matter (a description change can shift routing on cases targeting *other* skills; see asta-plugins#67 for a routing-competition example).

## 3. Run baseline

Set up a clean `origin/main` worktree for the baseline:

```bash
[ -d "$DEV_ROOT/agent-baselines" ] || git clone git@github.com:allenai/agent-baselines "$DEV_ROOT/agent-baselines"
[ -d "$DEV_ROOT/asta-plugins" ]    || git clone git@github.com:allenai/asta-plugins "$DEV_ROOT/asta-plugins"
export ASTA_TOKEN="$(asta auth print-token --raw --refresh)"
git -C "$DEV_ROOT/asta-plugins" fetch -q origin
git -C "$DEV_ROOT/asta-plugins" worktree add --detach "$DEV_ROOT/asta-plugins-main" origin/main 2>/dev/null \
    || git -C "$DEV_ROOT/asta-plugins-main" checkout -q --detach origin/main
export ASTA_MAIN="$DEV_ROOT/asta-plugins-main"
```

From `$DEV_ROOT/agent-baselines`, define `eval_env` to run each `inspect` command in the `solvers/inspect-swe` project:

```bash
cd "$DEV_ROOT/agent-baselines"
eval_env() { uv run --project solvers/inspect-swe --no-group astabench \
    --with "$DEV_ROOT/asta-bench-private" --frozen --reinstall-package astabench-private -- "$@"; }
```

Run the full case set (behavior + guards) in one eval:

```bash
eval_env inspect eval astabench/asta_skills \
    --sample-id <case_id_1>,<case_id_2>,... \
    --solver agent_baselines/solvers/inspect_swe/agent.py@inspect_swe_solver \
    --sandbox docker:solvers/inspect-swe/sandbox_compose.yaml \
    --model anthropic/claude-sonnet-4-6 \
    --epochs 3 --working-limit 600 \
    -S agent=claude_code \
    -S strict_reproducibility=true \
    -S skills=$ASTA_MAIN/plugins/asta-tools/skills \
    --log-dir logs/baseline
# model & agent above are the asta-plugins low-cost convention
# -S version and the ASTA_IMAGE env var are left unset for baseline -> auto / :latest
```

Read per-case-per-metric scores: `eval_env inspect log dump --header-only "$(ls -t logs/baseline/*.eval | head -1)" | jq '.reductions[0].samples'`. For every arm you run (here and in steps 5–6), also read the transcript (`eval_env inspect view --log-dir logs`, or the sample `messages`), not just the score — confirm the metric reflects the intended behavior, not a coincidence (the gap reproduces, any lift is real, a held guard isn't masking change). For a new case, its gap-capturing metric should score below ceiling; if at ceiling, the gap isn't reproducing — investigate.

> **If stopping here (reproducible test + baseline, TDD red):** file an issue per step 1 with a `## Reproducible test` section — the baseline numbers, the transcript read (so the fixer inherits the *why*, not just the number), and the case(s): link the asta-bench-private PR if you added any (push the branch, open the PR), or name the existing case(s) you reused.

## 4. Make the skill change(s)

From the baseline transcript, hypothesize why the skill(s) produce the gap and what will close it.

```bash
# Worktree for the PR branch:
git -C "$DEV_ROOT/asta-plugins" worktree add "$DEV_ROOT/asta-plugins-<pr-branch>" -b <pr-branch>
```

Then, in `$DEV_ROOT/asta-plugins-<pr-branch>`, edit existing skill(s) or add a new one under `plugins/asta-tools/skills/<name>/` (user-facing skills), `plugins/asta-flows/skills/<name>/` (autonomous-research drivers), or `plugins/asta-dev/skills/<name>/` (contributor skills) — edit them directly. Fixes may span multiple skills. Commit and push:

```bash
cd "$DEV_ROOT/asta-plugins-<pr-branch>"
git add -A && git commit -m "<summary>" && git push -u origin <pr-branch>
```

## 5. Run the PR arm (same case set)

Back in `$DEV_ROOT/agent-baselines`, pin to what the baseline resolved:

```bash
eval "$(eval_env inspect log dump "$(ls -t logs/baseline/*.eval | head -1)" | jq -er '.samples[0].metadata
    | "ASTA_IMAGE=\(.asta_image)\nAGENT_VERSION=\(.agent_version)"')"
export ASTA_IMAGE   # env var the sandbox compose substitutes into `image: ${ASTA_IMAGE}` (no flag sets the image); AGENT_VERSION stays a shell var for -S version below
```

Rerun the step-3 eval with the exported `ASTA_IMAGE` and:

- `-S version="$AGENT_VERSION"`
- `-S skills=$DEV_ROOT/asta-plugins-<pr-branch>/plugins/asta-tools/skills`
- `--log-dir logs/pr-arm`

Confirm new-case metrics fire and the regression guards hold at baseline. If a guard drops, your change regressed that case — find the cause and fix it (or explain it if the drop is benign) before opening the PR.

## 6. Ablation

For a multi-part fix, hypothesize which parts carry the result and which may be unnecessary or harmful, then ablate to test (e.g. asta-plugins#67).

Create the variant — a worktree off the PR branch with one part undone:

```bash
git -C "$DEV_ROOT/asta-plugins-<pr-branch>" worktree add "$DEV_ROOT/asta-plugins-ablate" -b ablate-<short-desc>
cd "$DEV_ROOT/asta-plugins-ablate"
git checkout main -- plugins/asta-tools/skills/<skill>/SKILL.md   # undo one part: a whole file, or hand-edit to undo part of one
git add -A && git commit -m "ablate: <description>"
```

Rerun the step-5 eval on the variant (keeping its `-S version` pin and exported `ASTA_IMAGE`) with:

- `-S skills=$DEV_ROOT/asta-plugins-ablate/plugins/asta-tools/skills`
- `--log-dir logs/ablation`

A drop from the PR arm means that part is load-bearing — keep it. No drop means it isn't pulling weight — drop it from the PR (or note why it stays). If undoing a part recovers a regressed guard, it was causing that regression — drop or rework it.

## 7. Open the PR(s)

Draft a body per repo you touched, in `<project-root>/.asta/improve-skills/` as `<slug>-<repo>-pr.md` — concise, linking the companion rather than restating it:

- **asta-plugins** (always): what it fixes — `Resolves #<issue>` if one exists, else the gap and the behavior it addresses — plus **Validation**: pinned setup (agent version, model, image tag + `@sha256:`), an arms table (baseline, PR, and ablation if you ran one) across cases and metrics, and the transcript read.
- **asta-bench-private** (only if you changed cases): the case(s) and what they measure; defer results to the companion.

Create each with `gh pr create --repo allenai/<repo> --body-file <project-root>/.asta/improve-skills/<slug>-<repo>-pr.md`, then cross-link their numbers with `gh pr edit`.

If you ran an ablation, tag its variant and link it from the asta-plugins PR's validation section (`https://github.com/allenai/asta-plugins/tree/experiments/PR-<num>/<short-desc>`) so reviewers can reproduce it:

```bash
git -C "$DEV_ROOT/asta-plugins-ablate" tag -a experiments/PR-<num>/<short-desc> -m "PR #<num> minus <part> — ablation arm."
git -C "$DEV_ROOT/asta-plugins-ablate" push origin refs/tags/experiments/PR-<num>/<short-desc>
```
