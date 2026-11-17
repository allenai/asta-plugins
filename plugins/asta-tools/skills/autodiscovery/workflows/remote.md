# AutoDS, remote

We pay for it, in Asta credits: one credit per experiment. The data goes to Asta's servers and the runs execute there.

The person logs in once: `asta auth login` (in Claude Code, `! asta auth login`). Check the balance before suggesting a budget: `asta autodiscovery credits`.

## A run

```bash
RUNID=$(asta autodiscovery create)
asta autodiscovery upload "$RUNID" <data files>
asta autodiscovery metadata "$RUNID" --file metadata.json
asta autodiscovery metadata-get "$RUNID"          # check the name, prompt, files and count before you submit
asta autodiscovery submit "$RUNID" -y             # -y skips the prompt; check credits before and after
asta autodiscovery status "$RUNID"                # PENDING, RUNNING, then SUCCEEDED
asta autodiscovery results "$RUNID" -o results.json --cache-dir <dir>
```

- `upload` prints `done (<bytes>)` per file; that, not `metadata-get`, shows the file landed.
- `--cache-dir` keeps finished experiments, so a rerun while the run goes fetches only new ones. `results.json` carries the plots as base64 and can be several MB.
- Credits show as Pending at submit and move to Consumed as experiments finish.

**The next round** is a fork, which copies the run's metadata and files:

```bash
NEW=$(asta autodiscovery fork "$RUNID")
asta autodiscovery metadata-get "$NEW" > round2.json   # set n_experiments to 50, and the intent below
asta autodiscovery metadata "$NEW" --file round2.json
asta autodiscovery submit "$NEW" -y
```

The intent drills into the picks: "Explore further: <what each pick was about>".

Other commands: `runs`, `run <runid>`, `experiments <runid>`, `experiment <runid> <node id>`. They print JSON, or `--format text` to show someone.

An experiment takes 1 to 2.5 minutes, so 50 take one to two hours. Save each round's `results.json` in its own folder (`round-1/`, `round-2/`) as soon as it finishes. To share a run, share it in the AutoDiscovery app, then open one experiment link in a private window to check it needs no sign-in.

## metadata.json

```json
{
  "name": "<short name>",
  "description": "<the run's context: where the data came from, how it was collected, its gaps>",
  "domain": "<the field>",
  "intent": "<the prompt>",
  "datasets": [{"name": "<file name as uploaded>", "description": "<the file's description>",
                "content_type": "text/csv", "file_size_bytes": 1048576, "is_preloaded": false}],
  "n_experiments": 50
}
```

The run's context (where the data came from, how it was collected) goes in the top-level `description`; each file's description, column by column, goes in its `datasets[].description`. `file_size_bytes` is the file's size (`stat -f %z` on macOS, `stat -c %s` on Linux). `name`, `datasets` and `n_experiments` (1 to 500) are required. The search settings are optional, and the defaults suit most runs:

| Setting | Default | Higher means |
|---|---|---|
| `exploration_weight` | 1.0 | broader (3 to 5); lower goes deeper on what's promising |
| `surprisal_width` | 0.5 | only big shifts count as surprising |
| `evidence_weight` | 1.0 | trusts the data more |
| `mcts_selection` | `ucb1_recursive` | `pw` (progressive widening) for a very large space |

Files go straight to storage, up to 50 GB each.
