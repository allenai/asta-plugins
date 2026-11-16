# Skill runs

These check that the skills work on a real run, not just that they parse. Each case gives a fresh headless Claude Code agent one small task to do by following a skill as written, then checks the files it left behind. The agent also writes `FEEDBACK.md`: every instruction it followed, and whether it worked.

```bash
python3 skill-runs/run.py --list                      # the cases, and what each spends
python3 skill-runs/run.py autods-cli                  # one case
python3 skill-runs/run.py all
```

You need:

- `claude` (Claude Code) on PATH;
- a `KEY=value` file with `ANTHROPIC_API_KEY`, plus the tool keys a case uses (`OPENAI_API_KEY`, `S2_API_KEY`, `MISTRAL_API_KEY`). Pass it with `--env-file`, or set `SKILL_RUNS_ENV_FILE`. The agent's shell gets only the tool keys its case needs; Claude reads its own through a helper.
- `asta auth login`, for the hosted cases. They spend Asta credits, and the report says how many.

Until Theorizer 0.1.5 is on PyPI, pass `--theorizer <a checkout or a wheel>` for the Theorizer cases.

Each agent runs with `--bare` (no CLAUDE.md, memory or hooks), only this repo's plugins, a spend cap, and `--permission-mode dontAsk`. Any tool a skill needs but doesn't list in its `allowed-tools` shows up as a denied tool in the report, which is a finding too.

Results go to `skill-runs/results/<time>/`, one folder per case: the prompt, Claude's output, `report.json`, and the agent's work folder with its `FEEDBACK.md`. `summary.md` has the table.

The penguins data in `fixtures/` is the Palmer Station penguins table, CC0.
