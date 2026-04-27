"""Shared helper: upload a local file to DV via the /upload_url endpoint.

Two-step presigned-URL flow, stdlib only (no new deps). Pattern reference:
asta/autodiscovery/client.py:102-142.
"""

from __future__ import annotations

import json
import mimetypes
import os
import re
import urllib.parse
import urllib.request
from typing import Any

# Matches the server-side validation in dv-core's upload_routes.FILENAME_RE.
# We mirror it locally to fail before the round-trip when we can.
_FILENAME_RE = re.compile(r"^[A-Za-z0-9._\- ]{1,256}$")
_MAX_BYTES = 5 * 1024 * 1024 * 1024  # 5 GiB — single-PUT limit

_PUT_TIMEOUT = 600  # seconds, matches autodiscovery/client.py
_GET_TIMEOUT = 30


def upload_local_file(
    base_url: str,
    token: str | None,
    path: str,
    *,
    filename: str | None = None,
) -> dict[str, Any]:
    """GET {base_url}/upload_url, then PUT the file bytes.

    Returns {s3_uri, filename, size, content_type}.

    Raises:
        FileNotFoundError: path doesn't exist.
        ValueError: file > 5 GiB, or filename fails validation.
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

    upload_name = filename or os.path.basename(path)
    if ".." in upload_name or not _FILENAME_RE.match(upload_name):
        raise ValueError(
            f"Invalid filename {upload_name!r}: must match "
            "^[A-Za-z0-9._\\- ]{1,256}$ and contain no '..'"
        )

    content_type = mimetypes.guess_type(upload_name)[0] or "application/octet-stream"

    presign = _get_presigned(base_url, token, upload_name, content_type)

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
    base_url: str, token: str | None, filename: str, content_type: str
) -> dict[str, Any]:
    query = urllib.parse.urlencode(
        {"filename": filename, "content_type": content_type}
    )
    url = f"{base_url.rstrip('/')}/upload_url?{query}"
    headers = {"Accept": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(req, timeout=_GET_TIMEOUT) as resp:
        return json.loads(resp.read())
