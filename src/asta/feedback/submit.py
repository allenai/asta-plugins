"""`asta feedback submit` — upload a reviewed feedback directory in one shot.

The ``feedback`` skill populates DIRECTORY with a ``FEEDBACK.md`` narrative and
optional supporting reports, and lets the user review it. This command then
does the whole submission as a single operation:

1. bundle DIRECTORY into a gzip-tar (client-side, with size gates),
2. ask the Gateway to mint a submission id + presigned GCS upload URL,
3. upload the bundle straight to GCS.

Auth comes from ``asta auth login`` (or ``ASTA_TOKEN``).
"""

from __future__ import annotations

import json
from pathlib import Path

import click

from asta.feedback._bundle import build_bundle
from asta.feedback._client import (
    BUNDLE_CONTENT_TYPE,
    create_submission,
    upload_bundle,
)
from asta.feedback._url import feedback_url
from asta.utils.auth_helper import get_access_token


@click.command()
@click.argument(
    "directory",
    type=click.Path(exists=True, file_okay=False, dir_okay=True, readable=True),
)
@click.option(
    "--dry-run",
    is_flag=True,
    help="Build and validate the bundle and print its manifest, but don't upload.",
)
def submit(directory: str, dry_run: bool) -> None:
    """Submit the feedback in DIRECTORY.

    DIRECTORY must contain a ``FEEDBACK.md`` narrative; any other files are
    uploaded alongside it as supporting material.
    """
    try:
        bundle = build_bundle(directory)
    except (FileNotFoundError, ValueError) as e:
        raise click.ClickException(str(e)) from e

    click.echo(
        f"Bundled {bundle.num_files} file(s), "
        f"{bundle.total_bytes / 1024:.1f} KiB uncompressed "
        f"({len(bundle.data) / 1024:.1f} KiB compressed).",
        err=True,
    )

    if dry_run:
        click.echo(json.dumps(bundle.manifest, indent=2, sort_keys=True))
        return

    token = get_access_token()
    base_url = feedback_url()
    # The submission directory name is the slug; the server pairs it with the
    # caller's identity to form the submission id (<user_id>/<slug>).
    slug = Path(directory).resolve().name or "feedback"

    try:
        submission = create_submission(
            base_url,
            token,
            slug=slug,
            filename="bundle.tar.gz",
            size_bytes=len(bundle.data),
            num_files=bundle.num_files,
            content_type=BUNDLE_CONTENT_TYPE,
        )
    except Exception as e:
        raise click.ClickException(f"Failed to create submission: {e}") from e

    try:
        upload_bundle(submission["upload_url"], bundle.data)
    except Exception as e:
        raise click.ClickException(f"Failed to upload feedback bundle: {e}") from e

    click.echo(f"✅ Feedback submitted. Submission id: {submission['submission_id']}")
