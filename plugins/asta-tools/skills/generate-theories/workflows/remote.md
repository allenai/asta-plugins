# Theorizer, remote

We pay for it. Theorizer runs on Asta's servers, so the question and the papers go there.

The person logs in once: `asta auth login` (in Claude Code, `! asta auth login`).

The commands are generated from the service's agent card, so once logged in, ask them what they take: `asta generate-theories --help`, `asta generate-theories card`, and `asta generate-theories describe <skill>` for one skill's inputs. Before login, only `card`, `send-message` and `task` show, and `card` says to log in.

## The skills

| Skill | What it does |
|---|---|
| `build-extraction-schema` | Plans the search query and drafts the extraction schema, to look at or edit before a run |
| `find-and-extract` | Finds papers and extracts findings from each with the schema |
| `form-theory` | Writes theories from an earlier run (`--run-id`), or from extraction results you give it |
| `evaluate-novelty` | Scores each law as established, derivable from known work, or new (`--run-id`) |
| `literature-theory-generation` | All three back to back |
| `resume-extraction` | Adds papers to an earlier run and extracts from them |

## A run

On the first run in a session, ask once whether to run it straight through (`literature-theory-generation`) or stage by stage (`find-and-extract`, then `form-theory`, then `evaluate-novelty`), unless the person already said. Stage by stage, after each one show what came out (the papers and what was extracted from each, then the theories with their evidence counts, then the novelty labels in plain words), and ask whether to go on, stop or change something.

Before you submit, say what's going in, in one line: "Using N papers, novelty evaluation on, accuracy-focused. Say 'tune' to change anything."

Each skill takes its fields as flags (`describe <skill>` lists them), or a payload file with `--input file.json`; flags override the file. The command polls by itself and prints the final task JSON on stdout when it's done (progress goes to stderr), so run it in the background with stdout to its result file, and wait; don't write your own loop:

```bash
asta generate-theories find-and-extract --theory-query '<the question>' --mission-statement '<mission>' > <run>/theory/find-and-extract.result.json
asta generate-theories form-theory --run-id <run id> --theory-query '<the question>' > <run>/theory/form-theory.result.json
```

The run id is the `gen-YYYYMMDD-xxxxxxxx` in the first task's `.metadata.run_id`, not its `task_id`. Pass `--theory-query` to `form-theory` again: the run doesn't keep it.

| Setting | Default | Change it when |
|---|---|---|
| `max_papers_to_retrieve` | 50 | 5 to 10 for a quick run (5 papers: about 8 minutes to extract, 8 more for theories), 100 for full coverage |
| `generation_objective` | `accuracy-focused` | `novelty-focused` when the person wants new theories |
| `do_qualified_novelty_evaluation` | `true` (adds 30 to 60 minutes); `literature-theory-generation` only | off for fast iteration; stage by stage, run `evaluate-novelty` or don't |

- **The mission statement goes in at `find-and-extract`** (or `literature-theory-generation`). `form-theory` has no field for it, so anything the theories must answer to has to be ready before the papers are found.
- **You can't set the number of theories.** No skill takes a count. Say so if the person asks for one.
- **No hosted skill discovers variables.** For a run's 4b, write the new schemas yourself and run `find-and-extract` on the same papers with each ([theory-generation.md](theory-generation.md), "Discovering variables").
- **Novelty is scored only by `evaluate-novelty`** (or `literature-theory-generation` with the evaluation on). The novelty label `form-theory` puts on each theory is its own guess, not a score; don't report it as one.

## When it's done

Keep each task's final JSON, as `<skill>.result.json` in the run's `theory/` folder (`find-and-extract.result.json`, `form-theory.result.json`), stdout only. Keep every stage's: papers found through citations appear only in a later stage's result. The workspace's theory pages read them from there with [theorizer-site-data](../scripts/theorizer-site-data), so the theories and papers work offline. Outside a workflow, hand it to the `artifacts` skill to export and index (slug `YYYY-MM-DD-<short-query-slug>`). Then reply with where it lives, how many papers had full text, a few sentences on what the theories argue together, and a table of the theories: name and core idea, the paper findings each cites, plus novelty if it was scored. Flag a theory that cites no paper findings: it rests on the mission alone.

- `state=input-required`: the command prints how to continue. Ask the person, then `asta generate-theories send-message --task-id <id> --context-id <ctx> '<reply>'`.
- `state=failed`: report `status.message` and stop.
- A stopped run can go on later: pass its run id (`--run-id`) to `form-theory` or `evaluate-novelty`.
