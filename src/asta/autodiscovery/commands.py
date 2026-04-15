"""AutoDiscovery CLI commands."""

import json
import os
from datetime import datetime

import click

from asta.autodiscovery.client import AutoDiscoveryClient

# -- Formatters ---------------------------------------------------------------


def _fmt_time(iso: str | None) -> str:
    if not iso:
        return "-"
    try:
        dt = datetime.fromisoformat(iso.replace("Z", "+00:00"))
        return dt.strftime("%Y-%m-%d %H:%M UTC")
    except (ValueError, TypeError):
        return iso


def _status_icon(status: str) -> str:
    s = status.upper()
    if s in ("SUCCEEDED", "COMPLETED"):
        return "[OK]"
    if s in ("RUNNING", "IN_PROGRESS"):
        return "[..]"
    if s in ("FAILED", "ERROR"):
        return "[!!]"
    if s in ("CANCELLED", "DELETED"):
        return "[XX]"
    if s == "PENDING":
        return "[--]"
    return f"[{s[:2]}]"


# -- CLI group ----------------------------------------------------------------


@click.group()
def autodiscovery():
    """AutoDiscovery - check runs and view experiment results."""
    pass


# -- Commands ------------------------------------------------------------------


@autodiscovery.command()
@click.option(
    "--format",
    "output_format",
    type=click.Choice(["json", "text"]),
    default="json",
    help="Output format",
)
def runs(output_format):
    """List all runs for the authenticated user."""
    try:
        data = AutoDiscoveryClient().list_runs()
    except Exception as e:
        raise click.ClickException(str(e))

    if output_format == "json":
        click.echo(json.dumps(data, indent=2))
        return

    runs_list = data.get("runs", [])
    if not runs_list:
        click.echo("No runs found.")
        return

    click.echo(
        f"{'Status':<8} {'Name':<35} {'Experiments':<14} {'Created':<22} {'Run ID'}"
    )
    click.echo("-" * 110)
    for r in runs_list:
        stats = r.get("run_stats") or {}
        details = r.get("run_details") or {}
        exp = f"{stats.get('completed_experiments', '?')}/{stats.get('requested_experiments', '?')}"
        click.echo(
            f"{_status_icon(r.get('status', '?')):<8} "
            f"{(r.get('name') or 'Untitled')[:34]:<35} "
            f"{exp:<14} "
            f"{_fmt_time(details.get('created_at')):<22} "
            f"{r.get('runid', '?')}"
        )


@autodiscovery.command()
@click.argument("runid")
@click.option(
    "--format",
    "output_format",
    type=click.Choice(["json", "text"]),
    default="json",
    help="Output format",
)
def run(runid, output_format):
    """Get details for a specific run."""
    try:
        data = AutoDiscoveryClient().get_run(runid)
    except Exception as e:
        raise click.ClickException(str(e))

    if output_format == "json":
        click.echo(json.dumps(data, indent=2))
        return

    details = data.get("run_details") or {}
    stats = data.get("run_stats") or {}
    metadata = data.get("run_metadata") or {}

    click.echo(f"Run: {data.get('name') or metadata.get('name') or 'Untitled'}")
    click.echo(f"  ID:         {data.get('runid', runid)}")
    click.echo(f"  Status:     {data.get('status', '?')}")
    click.echo(f"  Created:    {_fmt_time(details.get('created_at'))}")
    click.echo(f"  Finished:   {_fmt_time(details.get('finished_at'))}")
    if details.get("execution_id"):
        click.echo(f"  Execution:  {details['execution_id']}")

    if stats:
        click.echo("\n  Experiments:")
        click.echo(f"    Requested:  {stats.get('requested_experiments', '?')}")
        click.echo(f"    Completed:  {stats.get('completed_experiments', '?')}")
        click.echo(f"    Pending:    {stats.get('pending_experiments', '?')}")
        click.echo(f"    Surprising: {stats.get('num_surprising_experiments', '?')}")

    if metadata.get("description"):
        click.echo(f"\n  Description: {metadata['description']}")
    if metadata.get("domain"):
        click.echo(f"  Domain:      {metadata['domain']}")
    if datasets := metadata.get("datasets"):
        click.echo("  Datasets:")
        for ds in datasets:
            desc = f" ({ds['description']})" if ds.get("description") else ""
            click.echo(f"    - {ds.get('name', 'unnamed')}{desc}")


@autodiscovery.command()
@click.argument("runid")
@click.option(
    "--format",
    "output_format",
    type=click.Choice(["json", "text"]),
    default="json",
    help="Output format",
)
def status(runid, output_format):
    """Check the current execution status of a run."""
    try:
        data = AutoDiscoveryClient().get_status(runid)
    except Exception as e:
        raise click.ClickException(str(e))

    if output_format == "json":
        click.echo(json.dumps(data, indent=2))
        return

    details = data.get("run_details", {})
    click.echo(f"Run {runid}:")
    click.echo(f"  Status:       {details.get('status', '?')}")
    click.echo(f"  Last checked: {_fmt_time(details.get('status_checked_at'))}")
    click.echo(f"  Created:      {_fmt_time(details.get('created_at'))}")
    click.echo(f"  Finished:     {_fmt_time(details.get('finished_at'))}")


@autodiscovery.command()
@click.argument("runid")
@click.option(
    "--format",
    "output_format",
    type=click.Choice(["json", "text"]),
    default="json",
    help="Output format",
)
def experiments(runid, output_format):
    """List all experiments in a run."""
    try:
        data = AutoDiscoveryClient().list_experiments(runid)
    except Exception as e:
        raise click.ClickException(str(e))

    if output_format == "json":
        click.echo(json.dumps(data, indent=2))
        return

    exps = data.get("experiments", [])
    if not exps:
        click.echo("No experiments found.")
        return

    completed = data.get("has_job_completed", False)
    click.echo(f"Run {runid} -- {'completed' if completed else 'in progress'}")
    click.echo(
        f"{'#':<5} {'Status':<8} {'Surprising':<12} "
        f"{'Surprise':<10} {'Prior':<8} {'Post':<8} {'Hypothesis'}"
    )
    click.echo("-" * 110)

    for exp in sorted(exps, key=lambda e: e.get("creation_idx", 0)):
        idx = exp.get("id_in_run", exp.get("creation_idx", "?"))
        surprising = (
            "yes"
            if exp.get("is_surprising")
            else ("no" if exp.get("is_surprising") is False else "-")
        )
        surprise = f"{exp['surprise']:.3f}" if exp.get("surprise") is not None else "-"
        prior = f"{exp['prior']:.3f}" if exp.get("prior") is not None else "-"
        posterior = (
            f"{exp['posterior']:.3f}" if exp.get("posterior") is not None else "-"
        )
        hypothesis = (exp.get("hypothesis") or "-")[:50]

        click.echo(
            f"{idx:<5} {_status_icon(exp.get('status', '?')):<8} "
            f"{surprising:<12} {surprise:<10} {prior:<8} {posterior:<8} "
            f"{hypothesis}"
        )


@autodiscovery.command()
@click.argument("runid")
@click.argument("experiment_id")
@click.option(
    "--format",
    "output_format",
    type=click.Choice(["json", "text"]),
    default="json",
    help="Output format",
)
def experiment(runid, experiment_id, output_format):
    """Get details for a specific experiment."""
    try:
        data = AutoDiscoveryClient().get_experiment(runid, experiment_id)
    except Exception as e:
        raise click.ClickException(str(e))

    if output_format == "json":
        click.echo(json.dumps(data, indent=2))
        return

    exp = data.get("experiment")
    if not exp:
        click.echo(f"Experiment {experiment_id} not found in run {runid}.")
        return

    click.echo(f"Experiment: {exp.get('experiment_id', experiment_id)}")
    click.echo(f"  Status:      {exp.get('status', '?')}")
    click.echo(f"  Created:     {_fmt_time(exp.get('created_at'))}")
    if exp.get("runtime_ms") is not None:
        click.echo(f"  Runtime:     {exp['runtime_ms'] / 1000:.1f}s")
    click.echo(f"  Surprising:  {'yes' if exp.get('is_surprising') else 'no'}")
    if exp.get("surprise") is not None:
        click.echo(f"  Surprise:    {exp['surprise']:.4f}")
    if exp.get("prior") is not None:
        click.echo(f"  Prior:       {exp['prior']:.4f}")
    if exp.get("posterior") is not None:
        click.echo(f"  Posterior:   {exp['posterior']:.4f}")

    if exp.get("hypothesis"):
        click.echo(f"\n  Hypothesis:\n    {exp['hypothesis']}")
    if exp.get("analysis"):
        click.echo(f"\n  Analysis:\n    {exp['analysis'][:500]}")
    if exp.get("review"):
        click.echo(f"\n  Review:\n    {exp['review'][:500]}")
    if exp.get("code"):
        click.echo(f"\n  Code:\n    {exp['code'][:1000]}")
    if exp.get("code_output"):
        click.echo(f"\n  Code output:\n    {exp['code_output'][:1000]}")
    if exp.get("rich_outputs"):
        click.echo(f"\n  Rich outputs: {len(exp['rich_outputs'])} item(s)")
    if exp.get("parent_id"):
        click.echo(f"\n  Parent: {exp['parent_id']}")
    if exp.get("child_ids"):
        click.echo(f"  Children: {', '.join(exp['child_ids'])}")


# -- Run creation commands -----------------------------------------------------


@autodiscovery.command()
def create():
    """Create a new empty run. Prints the run ID."""
    try:
        data = AutoDiscoveryClient().create_run()
    except Exception as e:
        raise click.ClickException(str(e))

    click.echo(data["runid"])


@autodiscovery.command()
@click.argument("runid")
@click.argument("files", nargs=-1, required=True, type=click.Path(exists=True))
def upload(runid, files):
    """Upload one or more dataset files to a run."""
    try:
        client = AutoDiscoveryClient()
    except Exception as e:
        raise click.ClickException(str(e))

    for filepath in files:
        filename = os.path.basename(filepath)
        click.echo(f"Uploading {filename}...", nl=False)
        try:
            result = client.upload_file(runid, filepath)
            click.echo(f" done ({result['file_size_bytes']} bytes)")
        except Exception as e:
            click.echo(" FAILED")
            raise click.ClickException(f"Failed to upload {filename}: {e}")


@autodiscovery.command()
@click.argument("runid")
@click.option(
    "--file",
    "-f",
    "filepath",
    required=True,
    type=click.Path(exists=True),
    help="Path to metadata JSON file",
)
def metadata(runid, filepath):
    """Save metadata for a run from a JSON file."""
    try:
        with open(filepath) as f:
            meta = json.load(f)
    except json.JSONDecodeError as e:
        raise click.ClickException(f"Invalid JSON in {filepath}: {e}")

    try:
        data = AutoDiscoveryClient().save_metadata(runid, meta)
    except Exception as e:
        raise click.ClickException(str(e))

    click.echo(f"Metadata saved: {data.get('path', 'ok')}")


@autodiscovery.command(name="metadata-get")
@click.argument("runid")
def metadata_get(runid):
    """Get metadata for an existing run (JSON output)."""
    try:
        data = AutoDiscoveryClient().get_metadata(runid)
    except Exception as e:
        raise click.ClickException(str(e))

    click.echo(json.dumps(data.get("metadata", data), indent=2))


@autodiscovery.command()
@click.argument("runid")
@click.option("--yes", "-y", is_flag=True, help="Skip confirmation prompt")
def submit(runid, yes):
    """Submit a run for execution."""
    try:
        client = AutoDiscoveryClient()

        if not yes:
            # Show credit info before submitting
            try:
                credits = client.get_credits().get("credits", {})
                meta = client.get_metadata(runid).get("metadata", {})
                n_exp = meta.get("n_experiments", "?")
                click.echo(
                    f"Experiments: {n_exp}  |  "
                    f"Credits available: {credits.get('available', '?')}"
                )
                if not click.confirm("Submit this run?"):
                    raise SystemExit(0)
            except click.ClickException:
                raise
            except SystemExit:
                raise
            except Exception:
                pass  # proceed without credit info if lookup fails

        data = client.submit_run(runid)
    except click.ClickException:
        raise
    except SystemExit:
        raise
    except Exception as e:
        raise click.ClickException(str(e))

    details = data.get("run_details", {})
    click.echo(f"Submitted. Execution ID: {data.get('execution_id', '?')}")
    click.echo(f"Status: {details.get('status', '?')}")


@autodiscovery.command()
@click.argument("parent_runid")
def fork(parent_runid):
    """Fork an existing run (copies metadata and datasets)."""
    try:
        data = AutoDiscoveryClient().fork_run(parent_runid)
    except Exception as e:
        raise click.ClickException(str(e))

    click.echo(data["runid"])


@autodiscovery.command()
@click.option(
    "--format",
    "output_format",
    type=click.Choice(["json", "text"]),
    default="text",
    help="Output format",
)
def credits(output_format):
    """Show credit balance for the authenticated user."""
    try:
        data = AutoDiscoveryClient().get_credits()
    except Exception as e:
        raise click.ClickException(str(e))

    c = data.get("credits", {})
    if output_format == "json":
        click.echo(json.dumps(c, indent=2))
        return

    click.echo(f"Granted:   {c.get('granted', '?')}")
    click.echo(f"Consumed:  {c.get('consumed', '?')}")
    click.echo(f"Pending:   {c.get('pending', '?')}")
    click.echo(f"Available: {c.get('available', '?')}")
