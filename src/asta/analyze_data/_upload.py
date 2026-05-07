"""Internal helpers for staging local files into the DataVoyager workspace.

Two-step presigned-URL flow, stdlib only (no new deps). Pattern reference:
asta/autodiscovery/client.py:102-142.

The server is authoritative for the final S3 key — it constructs
``s3://<bucket>/<prefix>/<sub>/context/<context_id>/<filename>`` from the
caller's JWT and the supplied ``context_id``. We forward whatever ``s3_uri``
the presign response contains rather than recomputing it client-side.

Called by ``submit`` to upload caller-supplied files before issuing the
analysis request; not exposed as a standalone Click command.
"""

from __future__ import annotations

import json
import mimetypes
import os
import urllib.parse
import urllib.request
from typing import Any

_MAX_BYTES = 5 * 1024 * 1024 * 1024  # 5 GiB — single-PUT limit
_PUT_TIMEOUT = 600  # seconds, matches autodiscovery/client.py
_GET_TIMEOUT = 30


def upload_local_file(
    base_url: str,
    token: str | None,
    path: str,
    context_id: str,
) -> dict[str, Any]:
    """GET {base_url}/upload_url, then PUT the file bytes.

    Returns {s3_uri, filename, size, content_type}. ``s3_uri`` is whatever
    the server returns — we don't reconstruct it locally.

    Raises:
        FileNotFoundError: path doesn't exist.
        ValueError: file > 5 GiB, or filename contains '..'.
        urllib.error.HTTPError: server-side failure (401, 400, etc.).
    """
    if not os.path.exists(path):
        raise FileNotFoundError(f"No such file: {path}")

    size = os.path.getsize(path)
    if size >= _MAX_BYTES:
        gb = size / (1024**3)
        raise ValueError(
            f"File is {gb:.2f} GiB; single-PUT uploads are limited to 5 GiB. "
            "Multipart upload is not yet supported."
        )

    upload_name = os.path.basename(path)
    # Path-traversal guard only — the server enforces the full filename regex.
    # Filename collisions across uploads are tolerated because the S3 key is
    # namespaced under context/<context_id>/, so two uploads of `sales.csv`
    # in different sessions don't conflict.
    if ".." in upload_name:
        raise ValueError(f"Invalid filename {upload_name!r}: contains '..'")

    content_type = mimetypes.guess_type(upload_name)[0] or "application/octet-stream"

    presign = _get_presigned(base_url, token, upload_name, content_type, context_id)

    with open(path, "rb") as f:
        body = f.read()
    req = urllib.request.Request(
        presign["upload_url"],
        data=body,
        method="PUT",
        headers={"Content-Type": content_type},
    )
    with urllib.request.urlopen(req, timeout=_PUT_TIMEOUT) as resp:
        resp.read()

    return {
        "s3_uri": presign["s3_uri"],
        "filename": upload_name,
        "size": size,
        "content_type": content_type,
    }


def _get_presigned(
    base_url: str,
    token: str | None,
    filename: str,
    content_type: str,
    context_id: str,
) -> dict[str, Any]:
    query = urllib.parse.urlencode(
        {
            "filename": filename,
            "content_type": content_type,
            "context_id": context_id,
        }
    )
    url = f"{base_url.rstrip('/')}/upload_url?{query}"
    headers = {"Accept": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(req, timeout=_GET_TIMEOUT) as resp:
        return json.loads(resp.read())
