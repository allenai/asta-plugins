import importlib.util
import json
import os
import subprocess
import tempfile
import unittest
import warnings
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

ROOT = Path(__file__).resolve().parent.parent
spec = importlib.util.spec_from_file_location("demo", ROOT / "scripts/build-demo.py")
demo = importlib.util.module_from_spec(spec)
spec.loader.exec_module(demo)


class DemoTests(unittest.TestCase):
    def test_fixed_edit_patch_applies_to_the_example_sources(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            for name in (
                "evidence.yml",
                "lit-review/index.qmd",
                "paper/main.tex",
                "references.bib",
            ):
                target = root / name
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes((ROOT / name).read_bytes())
            subprocess.run(["git", "init", "-q", str(root)], check=True)
            subprocess.run(
                [
                    "git",
                    "add",
                    "evidence.yml",
                    "lit-review/index.qmd",
                    "paper/main.tex",
                    "references.bib",
                ],
                cwd=root,
                check=True,
            )
            subprocess.run(
                [
                    "git",
                    "apply",
                    "--check",
                    "--3way",
                    str(ROOT / "scripts/demo-edits.patch"),
                ],
                cwd=root,
                check=True,
            )

    def test_outside_a_git_checkout_fails_before_creating_a_demo(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            with (
                patch.object(demo, "ROOT", root),
                patch.object(demo.refresh, "workflow_ref", return_value="fixture"),
                patch.dict(os.environ, {"GIT_CEILING_DIRECTORIES": str(root.parent)}),
                self.assertRaises(subprocess.CalledProcessError),
            ):
                demo.build(root / "_site")
            self.assertFalse((root / "_site").exists())

    def test_packager_requires_an_output_path(self):
        result = subprocess.run(
            [
                "python3",
                str(ROOT / "scripts/refresh-demo.py"),
                "build",
                "--old",
                "/nonexistent",
                "--new",
                "/nonexistent",
                "--generator",
                "/nonexistent",
                "--ref",
                "fixture",
                "--baseline-commit",
                "before",
                "--changed-commit",
                "after",
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(result.returncode, 2)
        self.assertIn("--output", result.stderr)

    def test_packaging_does_not_pollute_the_compared_sites(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            old, new = root / "old", root / "new"
            old.mkdir()
            new.mkdir()
            for site in (old, new):
                (site / "index.html").write_text("site")
                (site / "demo/showcase").mkdir(parents=True)
                (site / "demo/showcase/stale.html").write_text("previous demo")
                (site / "demo/index.html").write_text("<!-- template-demo-report -->")
            generator = root / "generator.py"
            generator.touch()
            paper = new / "paper-previews/paper"
            (paper / "html").mkdir(parents=True)
            (paper / "html-diff").mkdir()
            (paper / "preview.json").write_text('{"diff":true,"html_diff":true}')
            (paper / "what-changed.pdf").write_bytes(b"pdf")
            (paper / "html/index.html").write_text("paper")
            (paper / "html-diff/index.html").write_text("diff")
            args = SimpleNamespace(
                old=old,
                new=new,
                generator=generator,
                ref="fixture",
                baseline_commit="before",
                changed_commit="after",
                output=old / "demo/showcase",
            )

            def generate(command, **kwargs):
                output = Path(command[command.index("--out") + 1])
                self.assertFalse(output.is_relative_to(old))
                self.assertFalse(output.is_relative_to(new))
                for flag in ("--old", "--new"):
                    compared = Path(command[command.index(flag) + 1])
                    self.assertFalse((compared / "demo/showcase").exists())
                    self.assertEqual(
                        (compared / "demo/index.html").read_text(),
                        "<!-- template-demo-report -->",
                    )
                page = (
                    '<section class="page-diff changed" id="p-lit-review-index-html">'
                    + "<ins>new</ins><del>old</del>" * 3
                )
                output.write_text(page + '<a href="./demo/index.html">demo</a>')

            with (
                patch.object(demo.refresh, "workflow_ref", return_value="fixture"),
                patch.object(demo.refresh.subprocess, "run", side_effect=generate),
            ):
                self.assertNotIn(
                    "showcase/what-changed.html", (old / "demo/index.html").read_text()
                )
                demo.refresh.build(args)
                demo.refresh.build(args)
            demo_page = args.output / "demo/index.html"
            self.assertIn('href="../what-changed.html"', demo_page.read_text())
            self.assertEqual(
                (old / "demo/index.html")
                .read_text()
                .count('href="showcase/what-changed.html"'),
                1,
            )
            self.assertIn(
                "<!-- template-demo-report -->", (new / "demo/index.html").read_text()
            )
            self.assertFalse((args.output / "demo/showcase").exists())

    def test_failed_packaging_does_not_publish_a_report_link(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            for name in ("old", "new"):
                site = root / name
                (site / "demo").mkdir(parents=True)
                (site / "index.html").write_text("site")
                (site / "demo/index.html").write_text("<!-- template-demo-report -->")
            generator = root / "generator.py"
            generator.touch()
            args = SimpleNamespace(
                old=root / "old",
                new=root / "new",
                generator=generator,
                ref="fixture",
                baseline_commit="before",
                changed_commit="after",
                output=root / "old/demo/showcase",
            )
            with (
                patch.object(
                    demo.refresh.subprocess,
                    "run",
                    side_effect=subprocess.CalledProcessError(1, "generator"),
                ),
                self.assertRaises(subprocess.CalledProcessError),
            ):
                demo.refresh.build(args)
            self.assertFalse(args.output.exists())
            self.assertEqual(
                (root / "old/demo/index.html").read_text(),
                "<!-- template-demo-report -->",
            )

    def test_missing_landing_placeholder_rejects_packaging(self):
        with tempfile.TemporaryDirectory() as temporary:
            page = Path(temporary) / "index.html"
            for content in ("no marker", "<!-- template-demo-report -->" * 2):
                page.write_text(content)
                with self.assertRaises(ValueError):
                    demo.refresh.report_link(page, "showcase/what-changed.html")

    def test_render_failure_restores_checkout_and_removes_worktree(self):
        self.check_render_failure()

    def test_failed_worktree_removal_prunes_metadata_and_preserves_render_error(self):
        self.check_render_failure(fail_cleanup=True)

    def test_dirty_checkout_is_rejected_before_creating_a_demo(self):
        self.check_render_failure(dirty=True)

    def check_render_failure(self, fail_cleanup=False, dirty=False):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)

            def git(*args):
                return subprocess.check_output(
                    ["git", "-C", str(root), *args], text=True
                ).strip()

            git("init", "-q")
            git("config", "user.name", "Demo test")
            git("config", "user.email", "demo@example.invalid")
            (root / ".gitignore").write_text(".asta/\n")
            files = (
                "evidence.yml",
                "lit-review/index.qmd",
                "paper/main.tex",
                "references.bib",
            )
            for name in files:
                path = root / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text("before\n")
            (root / "scripts").mkdir()
            (root / "scripts/demo-edits.patch").write_text(
                "--- a/paper/main.tex\n+++ b/paper/main.tex\n@@ -1 +1 @@\n-before\n+after\n"
                "--- a/review-notes.txt\n+++ b/review-notes.txt\n@@ -1 +1 @@\n-before\n+after\n"
            )
            (root / "review-notes.txt").write_text("before\n")
            (root / ".github/workflows").mkdir(parents=True)
            (root / ".github/workflows/docs.yml").write_text("workflow\n")
            git(
                "add",
                ".gitignore",
                "scripts/demo-edits.patch",
                "review-notes.txt",
                ".github/workflows/docs.yml",
                *files,
            )
            git("commit", "-qm", "Baseline")
            head = git("rev-parse", "HEAD")
            if dirty:
                (root / "references.bib").write_text("uncommitted change\n")

            original_run = demo.run

            def checked_run(*args, cwd=None, capture=False):
                if fail_cleanup and args[:3] == ("git", "worktree", "remove"):
                    raise subprocess.CalledProcessError(3, args)
                if args[0] == "make":
                    self.assertEqual(
                        original_run(
                            "git",
                            "show",
                            "HEAD:review-notes.txt",
                            cwd=cwd,
                            capture=True,
                        ),
                        "after",
                    )
                    raise subprocess.CalledProcessError(2, args)
                return original_run(*args, cwd=cwd or root, capture=capture)

            with (
                patch.object(demo, "ROOT", root),
                patch.object(demo.refresh, "workflow_ref", return_value="fixture"),
                patch.object(demo, "run", side_effect=checked_run),
                warnings.catch_warnings(record=True) as caught,
                self.assertRaises(
                    ValueError if dirty else subprocess.CalledProcessError
                ) as raised,
            ):
                demo.build(root / "_site")
            if dirty:
                self.assertIn("clean tracked checkout", str(raised.exception))
            else:
                self.assertEqual(raised.exception.returncode, 2)
            if fail_cleanup:
                self.assertTrue(
                    any("could not remove" in str(w.message) for w in caught)
                )
            self.assertEqual(git("rev-parse", "HEAD"), head)
            self.assertEqual(
                git("status", "--porcelain"), "M references.bib" if dirty else ""
            )
            self.assertEqual(
                git("worktree", "list", "--porcelain").count("worktree "), 1
            )
            self.assertFalse(any((root / ".git/worktrees").glob("*")))
            self.assertFalse((root / "demo/showcase").exists())

    def test_report_links_must_exist_inside_demo(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "manifest.json").write_text(
                json.dumps({"asta_plugins_ref": "fixture"})
            )
            paper = root / "paper-previews/paper"
            (paper / "html").mkdir(parents=True)
            (paper / "html-diff").mkdir()
            (paper / "preview.json").write_text('{"diff":true,"html_diff":true}')
            (paper / "what-changed.pdf").write_bytes(b"pdf")
            (paper / "html/index.html").write_text("paper")
            (paper / "html-diff/index.html").write_text("diff")
            page = (
                '<section class="page-diff changed" id="p-lit-review-index-html">'
                + "<ins>new</ins><del>old</del>" * 3
            )
            with patch.object(demo.refresh, "workflow_ref", return_value="fixture"):
                (root / "what-changed.html").write_text(
                    page + '<a href="paper-previews/paper/html/index.html">paper</a>'
                )
                demo.refresh.check(root)
                for link in ("missing.html", "../outside.html", "/outside.html"):
                    (root / "what-changed.html").write_text(
                        page + f'<a href="{link}">broken</a>'
                    )
                    with self.assertRaises(ValueError):
                        demo.refresh.check(root)


if __name__ == "__main__":
    unittest.main()
