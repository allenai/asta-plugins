"""Build the analyze-data tool-request envelope sent to dv-a2a-server.

The agent expects ``{kind: "analyze-data", data: {tool_request: {...}}}``.
``modal_app_name`` defaults to ``dv-core.prod``; setting
``ASTA_DV_MODAL_APP`` overrides for personal-env / rc testing.
"""

from __future__ import annotations

import os
from typing import Any

MODAL_APP_DEFAULT = "dv-core.prod"


def build_envelope(query: str, s3_uris: list[str]) -> dict[str, Any]:
    tool_request: dict[str, Any] = {
        "query": query,
        "modal_app_name": os.environ.get("ASTA_DV_MODAL_APP", MODAL_APP_DEFAULT),
    }
    if s3_uris:
        tool_request["datasets"] = list(s3_uris)
    return {"kind": "analyze-data", "data": {"tool_request": tool_request}}
