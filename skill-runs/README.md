# Skill runs

These check that the skills work on a real run, not just that they parse. They build up from pieces, each tool in each mode, to end-to-end runs of whole workflows; a workflow runs only if the pieces it uses passed in the same run. Each case gives a fresh headless Claude Code agent one small task to do by following a skill as written, then checks the files it left behind. The agent also writes `FEEDBACK.md`: every instruction it followed, and whether it worked.

```bash
python3 skill-runs/run.py --list                      # the cases, and what each spends
python3 skill-runs/run.py pieces                      # each tool in each mode
python3 skill-runs/run.py e2e                         # whole workflows
python3 skill-runs/run.py all                         # pieces first, then the workflows
python3 skill-runs/run.py autods-cli exploration-e2e  # or name cases
```

You need:

- `claude` (Claude Code) on PATH;
- the keys in the environment of the shell you start it from: `ANTHROPIC_API_KEY` for Claude, plus the tool keys a case uses (`OPENAI_API_KEY`, `S2_API_KEY` or `SEMANTIC_SCHOLAR_API_KEY`, `MISTRAL_API_KEY`). The agent's shell gets only the tool keys its case needs. Claude reads its own through a helper kept outside the agent's folders and deleted when the run ends.
- `asta auth login`, for the hosted cases. They spend Asta credits, and the report says how many.

Until Theorizer 0.1.5 is on PyPI, pass `--theorizer <a checkout or a wheel>` for the Theorizer cases.

Each agent runs with `--bare` (no CLAUDE.md, memory or hooks), only this repo's plugins, a spend cap, and `--permission-mode dontAsk`. Any tool a skill needs but doesn't list in its `allowed-tools` shows up as a denied tool in the report, which is a finding too.

Results go to `skill-runs/results/<time>/`, one folder per case: the prompt, Claude's output, `report.json`, and the agent's work folder with its `FEEDBACK.md`. `summary.md` has the table.

The penguins data in `fixtures/` is the Palmer Station penguins table, CC0.
