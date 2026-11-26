"""Translate Paper Finder's A2A v4 artifacts into ``LiteratureSearchResult``.

Each artifact's data part is a v4 ``search-result`` or ``report`` artifact
(mabool's ``a2a_v1/endpoints/v4/output.py``); both carry ``papers``.
"""

import sys
from typing import Any

from asta.literature.models import LiteratureSearchResult
from asta.literature.v4_papers import papers_of

EXPECTED_KIND_VERSION = "4"


def parse_artifacts(
    artifacts: list[dict[str, Any]],
    *,
    query: str,
    thread_id: str | None,
    narrative: str | None,
) -> LiteratureSearchResult:
    for artifact in artifacts:
        kind_version = artifact.get("kindVersion")
        if kind_version != EXPECTED_KIND_VERSION:
            print(
                f"warning: unexpected paper-finder artifact kindVersion={kind_version!r} "
                f"(expected {EXPECTED_KIND_VERSION!r}); proceeding best-effort",
                file=sys.stderr,
            )
    return LiteratureSearchResult(
        query=query,
        results=papers_of(artifacts),
        thread_id=thread_id,
        narrative=narrative,
    )
