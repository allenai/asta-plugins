# Hosted: we run it and pay for it

We pay for it. Theorizer and AutoDS run on Asta's servers, so the papers and data go there.

- The person logs in: `asta auth login` (in Claude Code, `! asta auth login`).
- Theorizer: the `generate-theories` skill.
- AutoDS: the `autodiscovery` skill's remote workflow.
- Save each result in the step's folder under `.asta/flows/` as soon as it finishes, so the workspace has everything.
