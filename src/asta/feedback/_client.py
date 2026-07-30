"""Transport for feedback submission: presigned-URL upload to GCS.

Two steps, stdlib only (pattern reference: ``asta/analyze_data/_upload.py``):

1. ``POST {base_url}/submissions`` with the caller's Bearer token. The Gateway
   mints a submission id, records the submitter's identity (from the JWT) and a
   server-side manifest, and returns a presigned GCS upload URL. This keeps the
   Gateway thin — it never sees the bundle bytes.
2. ``PUT`` the bundle bytes straight to the returned URL. The ``Content-Type``
   must match what the server signed, so we send it in step 1 and reuse it.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from typing import Any

BUNDLE_CONTENT_TYPE = "application/gzip"

_POST_TIMEOUT = 30  # seconds
_PUT_TIMEOUT = 600  # seconds — matches the analyze-data upload path


def create_submission(
    base_url: str,
    token: str | None,
    *,
    slug: str,
    filename: str,
    size_bytes: int,
    num_files: int,
    content_type: str = BUNDLE_CONTENT_TYPE,
) -> dict[str, Any]:
    """POST to mint a submission and obtain a presigned upload URL.

    ``slug`` names the submission; the server pairs it with the caller's
    identity to form the ``submission_id`` (``<user_id>/<slug>``).

    Returns the parsed response, which must contain ``submission_id`` and
    ``upload_url``; ``gcs_uri`` and ``expires_in`` are passed through when
    present.

    Raises:
        urllib.error.HTTPError / URLError: transport or server-side failure.
        ValueError: response is missing required fields.
    """
    body = json.dumps(
        {
            "slug": slug,
            "filename": filename,
            "content_type": content_type,
            "size_bytes": size_bytes,
            "num_files": num_files,
        }
    ).encode()
    headers = {"Content-Type": "application/json", "Accept": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"

    url = f"{base_url.rstrip('/')}/submissions"
    req = urllib.request.Request(url, data=body, method="POST", headers=headers)
    with urllib.request.urlopen(req, timeout=_POST_TIMEOUT) as resp:
        parsed = json.loads(resp.read())

    for field in ("submission_id", "upload_url"):
        if not parsed.get(field):
            raise ValueError(f"Feedback service response missing {field!r}: {parsed!r}")
    return parsed


def upload_bundle(upload_url: str, data: bytes) -> None:
    """PUT the bundle bytes to a GCS resumable-upload session URI.

    ``upload_url`` is the session URI returned by ``create_submission``. The
    object's content-type was fixed when the Gateway initiated the session, so
    the byte upload only needs a ``Content-Range`` spanning the whole payload
    (urllib sets ``Content-Length`` from ``data``). A single PUT covering the
    full range completes the upload.

    Raises:
        ValueError: empty payload (nothing to upload).
        urllib.error.HTTPError / URLError: the upload failed.
    """
    total = len(data)
    if total == 0:
        raise ValueError("Refusing to upload an empty bundle")
    req = urllib.request.Request(
        upload_url,
        data=data,
        method="PUT",
        headers={"Content-Range": f"bytes 0-{total - 1}/{total}"},
    )
    with urllib.request.urlopen(req, timeout=_PUT_TIMEOUT) as resp:
        resp.read()
