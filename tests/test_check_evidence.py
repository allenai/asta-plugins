from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

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


def test_minimal_yaml_parser_strips_plain_comments_and_rejects_flow_style() -> None:
    parsed = check_evidence._load_yaml_minimal(
        "evidence:\n  claim:\n    cite: smith2020  # explanatory comment\n"
    )

    assert parsed["evidence"]["claim"]["cite"] == "smith2020"
    with pytest.raises(ValueError, match="flow-style YAML requires PyYAML"):
        check_evidence._load_yaml_minimal("metadata-files: [evidence.yml]\n")
    with pytest.raises(ValueError, match="top-level YAML document must be a mapping"):
        check_evidence._load_yaml_minimal("- item\n")


def test_yaml_parsers_reject_duplicate_keys() -> None:
    duplicate = "evidence:\n  claim:\n    quote: first\n  claim:\n    quote: second\n"

    with pytest.raises(ValueError, match="duplicate YAML key 'claim'"):
        check_evidence._load_yaml(duplicate)
    with pytest.raises(ValueError, match="duplicate YAML key 'claim'"):
        check_evidence._load_yaml_minimal(duplicate)


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


def test_discover_follows_included_partials(tmp_path: Path) -> None:
    project = tmp_path / "project"
    project.mkdir()
    (project / "_quarto.yml").write_text("project:\n  render:\n    - index.qmd\n")
    index = project / "index.qmd"
    partial = project / "_intro.qmd"
    index.write_text("{{< include _intro.qmd >}}\n")
    partial.write_text('[partial claim]{.ev key="partial"}\n')

    _, _, qmds = check_evidence.discover(project)

    assert qmds == [str(partial.resolve()), str(index.resolve())]


def test_discover_follows_quoted_markdown_include_with_spaces(tmp_path: Path) -> None:
    project = tmp_path / "project"
    project.mkdir()
    (project / "_quarto.yml").write_text("project:\n  render:\n    - index.qmd\n")
    index = project / "index.qmd"
    partial = project / "_intro with spaces.md"
    index.write_text('{{< include "_intro with spaces.md" >}}\n')
    partial.write_text('[partial claim]{.ev key="partial"}\n')

    _, _, prose_paths = check_evidence.discover(project)

    assert prose_paths == [str(partial.resolve()), str(index.resolve())]


def test_discover_rejects_render_patterns_outside_root(tmp_path: Path) -> None:
    project = tmp_path / "project"
    project.mkdir()
    internal = project / "index.qmd"
    internal.write_text("internal\n")
    outside = tmp_path / "outside.qmd"
    outside.write_text("outside\n")
    (project / "_quarto.yml").write_text(
        f'''project:
  render:
    - "*.qmd"
    - "{outside}"
    - "!../outside.qmd"
'''
    )
    report = check_evidence.Report()

    _, _, qmds = check_evidence.discover(project, report)

    assert qmds == [str(internal.resolve())]
    assert report.errors == [
        (
            "_quarto.yml",
            0,
            f"`project.render` pattern must be relative to the project root: {outside}",
        ),
        (
            "_quarto.yml",
            0,
            "`project.render` pattern escapes the project root: ../outside.qmd",
        ),
    ]


def test_fallback_store_discovery_uses_path_components(tmp_path: Path) -> None:
    project = tmp_path / "research_site" / "project"
    project.mkdir(parents=True)
    store = project / "evidence.yml"
    store.write_text("evidence: {}\n")

    stores, _, _ = check_evidence.discover(project)

    assert stores == [str(store.resolve())]


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


def test_spans_accept_unquoted_attrs_and_ignore_multiline_inline_code(
    tmp_path: Path,
) -> None:
    page = tmp_path / "index.qmd"
    page.write_text(
        """[real claim]{.ev key=real quote="supporting text" cite=source}

`[multiline example]{.ev
key=ignored}`
"""
    )

    assert list(check_evidence.spans(page)) == [
        {
            "line": 1,
            "claim": "real claim",
            "attrs": {
                "key": "real",
                "quote": "supporting text",
                "cite": "source",
            },
        }
    ]


def test_spans_warn_on_unclosed_fence(tmp_path: Path) -> None:
    page = tmp_path / "index.qmd"
    page.write_text('before\n```markdown\n[hidden]{.ev key="hidden"}\n')
    report = check_evidence.Report()

    assert list(check_evidence.spans(page, report, "index.qmd")) == []
    assert report.warnings == [
        (
            "index.qmd",
            2,
            "unclosed fenced code block; evidence after it was skipped",
        )
    ]


def _write_project(project: Path, evidence: str, prose: str) -> None:
    project.mkdir()
    (project / "_quarto.yml").write_text(
        "bibliography: references.bib\nmetadata-files:\n  - evidence.yml\n"
    )
    (project / "references.bib").write_text("@misc{good}\n")
    (project / "evidence.yml").write_text(evidence)
    (project / "index.qmd").write_text(prose)


def test_main_accepts_valid_project(tmp_path: Path) -> None:
    project = tmp_path / "valid"
    _write_project(
        project,
        "evidence:\n  claim:\n    quote: supported\n    cite: good\n",
        '[claim]{.ev key="claim"}\n',
    )

    assert check_evidence.main(["--root", str(project)]) == 0


def test_main_reports_structural_errors_without_traceback(
    tmp_path: Path, capsys
) -> None:
    project = tmp_path / "invalid"
    _write_project(
        project,
        """evidence:
  missing-quote:
    cite: good
  bad-cite:
    quote: supported
    cite: absent
  orphan:
    quote: supported
    cite: good
  scalar-entry: not-a-mapping
""",
        """[dangling]{.ev key="dangling"}
[missing quote]{.ev key="missing-quote"}
[bad cite]{.ev key="bad-cite"}
""",
    )

    assert check_evidence.main(["--root", str(project)]) == 1
    stderr = capsys.readouterr().err
    assert "has no entry in the evidence store" in stderr
    assert "has no verbatim quote" in stderr
    assert 'cites "absent"' in stderr
    assert 'evidence entry "orphan" is not referenced' in stderr
    assert 'evidence entry "scalar-entry" must be a mapping' in stderr


@pytest.mark.parametrize(
    "filename, contents",
    [
        ("_quarto.yml", "project: [\n"),
        ("_quarto.yml", "project: not-a-mapping\n"),
        ("evidence.yml", "evidence: [\n"),
        ("evidence.yml", "- not-a-mapping\n"),
    ],
)
def test_main_reports_malformed_or_non_mapping_yaml(
    tmp_path: Path, capsys, filename: str, contents: str
) -> None:
    project = tmp_path / "malformed"
    _write_project(project, "evidence: {}\n", "")
    (project / filename).write_text(contents)

    assert check_evidence.main(["--root", str(project)]) == 1
    stderr = capsys.readouterr().err
    assert "invalid YAML" in stderr or "must be a mapping" in stderr


def test_github_annotations_escape_commands(monkeypatch, capsys) -> None:
    monkeypatch.setenv("GITHUB_ACTIONS", "true")
    report = check_evidence.Report()
    report.error("docs/a:b,c.qmd", 7, "bad 100%\r\nforged")

    assert report.emit() == 1
    stdout = capsys.readouterr().out
    assert "::error file=docs/a%3Ab%2Cc.qmd,line=7::bad 100%25%0D%0Aforged" in stdout


def test_bib_keys_accepts_empty_entries_and_ignores_comments(tmp_path: Path) -> None:
    bibliography = tmp_path / "references.bib"
    bibliography.write_text("% @misc{commented}\n@misc{empty}\n@article{full,}\n")

    assert check_evidence.bib_keys([bibliography]) == {"empty", "full"}
