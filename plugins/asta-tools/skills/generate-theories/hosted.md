# Theorizer hosted by Asta

We pay for it. Theorizer runs on Asta's servers, so the question and the papers go there.

The person logs in once: `asta auth login` (in Claude Code, `! asta auth login`).

The commands are generated from the service's agent card, so once logged in, ask them what they take: `asta generate-theories --help`, `asta generate-theories card`, and `asta generate-theories describe <skill>` for one skill's inputs. Before login, only `card`, `send-message`, `task` and `tasks` show, and `card` says to log in.

## The skills

| Skill | What it does |
|---|---|
| `build-extraction-schema` | Plans the search query and drafts the extraction schema, to look at or edit before a run |
| `find-and-extract` | Finds papers and extracts findings from each with the schema |
| `form-theory` | Writes theories from an earlier run's `task_id`, or from extraction results you give it |
| `evaluate-novelty` | Scores each law as established, derivable from known work, or new |
| `literature-theory-generation` | All three back to back |
| `resume-extraction` | Adds papers to an earlier run and extracts from them |

## A run

On the first run in a session, ask once whether to run it straight through (`literature-theory-generation`) or stage by stage (`find-and-extract`, then `form-theory`, then `evaluate-novelty`), unless the person already said. Stage by stage, after each one show what came out (the papers and what was extracted from each, then the theories with their evidence counts, then the novelty labels in plain words), and ask whether to go on, stop or change something.

Before you submit, say what's going in, in one line: "Using N papers, novelty evaluation on, accuracy-focused. Say 'tune' to change anything."

Each skill takes one JSON payload, inline or `@file.json`. The command polls by itself and prints the final task JSON when it's done, so run it in the background and wait; don't write your own loop.

| Setting | Default | Change it when |
|---|---|---|
| `max_papers_to_retrieve` | 10 (3 to 8 minutes) | 30 for a medium run, 100 for full coverage (15 to 25 minutes) |
| `generation_objective` | `accuracy-focused` | `novelty-focused` when the person wants new theories |
| `do_qualified_novelty_evaluation` | `true` (adds 30 to 60 minutes) | off for fast iteration |

## When it's done

Save the result in the step's folder as soon as it finishes. Outside a workflow, hand it to the `artifacts` skill to export and index (slug `YYYY-MM-DD-<short-query-slug>`). Then reply with where it lives, a few sentences on what the theories argue together, and a table of the theories: name and core idea, plus novelty if it was scored.

- `state=input-required`: the command prints how to continue. Ask the person, then `asta generate-theories send-message --task-id <id> --context-id <ctx> '<reply>'`.
- `state=failed`: report `status.message` and stop.
- A stopped run can go on later: pass its `task_id` to `form-theory` or `evaluate-novelty`.
