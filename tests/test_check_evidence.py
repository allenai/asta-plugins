from __future__ import annotations

import importlib.util
from pathlib import Path

SCRIPT = (
    Path(__file__).parents[1]
    / "plugins/asta-tools/skills/workspace/assets/check-evidence.py"
)
SPEC = importlib.util.spec_from_file_location("check_evidence", SCRIPT)
assert SPEC and SPEC.loader
check_evidence = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(check_evidence)


def test_minimal_yaml_parser_reads_block_quotes() -> None:
    parsed = check_evidence._load_yaml_minimal(
        """evidence:
  literal:
    quote: |
      first line
      second line
    cite: literal-ref
  folded:
    quote: >-
      first line
      second line
    cite: folded-ref
"""
    )

    assert parsed["evidence"]["literal"]["quote"] == "first line\nsecond line\n"
    assert parsed["evidence"]["folded"]["quote"] == "first line second line"


def test_discover_honors_root_and_render_exclusions(
    tmp_path: Path, monkeypatch
) -> None:
    project = tmp_path / "project"
    project.mkdir()
    (project / "_quarto.yml").write_text(
        """project:
  render:
    - "*.qmd"
    - "!excluded.qmd"
"""
    )
    (project / "evidence.yml").write_text("evidence: {}\n")
    (project / "references.bib").write_text("")
    included = project / "included.qmd"
    included.write_text("included\n")
    (project / "excluded.qmd").write_text("excluded\n")

    monkeypatch.chdir(tmp_path)
    stores, bibs, qmds = check_evidence.discover("project")

    assert stores == [str((project / "evidence.yml").resolve())]
    assert bibs == [str((project / "references.bib").resolve())]
    assert qmds == [str(included.resolve())]


def test_spans_ignore_code_and_comments(tmp_path: Path) -> None:
    page = tmp_path / "index.qmd"
    page.write_text(
        """[real claim]{.ev key="real"}

`[inline example]{.ev key="inline"}`

<!-- [commented example]{.ev key="comment"} -->

```markdown
[fenced example]{.ev key="fenced"}
```
"""
    )

    assert list(check_evidence.spans(page)) == [
        {"line": 1, "claim": "real claim", "attrs": {"key": "real"}}
    ]
