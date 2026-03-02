"""Tests for the Asta CLI."""

import json
from unittest.mock import MagicMock, patch

import pytest
from click.testing import CliRunner

from asta.cli import cli


@pytest.fixture
def runner():
    """Provide a Click CLI test runner."""
    return CliRunner()


class TestCLIBasics:
    """Test basic CLI functionality."""

    def test_version(self, runner):
        """Test --version flag."""
        result = runner.invoke(cli, ["--version"])
        assert result.exit_code == 0

    def test_help(self, runner):
        """Test --help flag."""
        result = runner.invoke(cli, ["--help"])
        assert result.exit_code == 0
        assert "Science literature research tools" in result.output
        assert "literature" in result.output

    def test_literature_help(self, runner):
        """Test literature subcommand help."""
        result = runner.invoke(cli, ["literature", "--help"])
        assert result.exit_code == 0
        assert "Literature research commands" in result.output
        assert "find" in result.output


class TestFindCommand:
    """Test 'asta literature find' command."""

    def test_find_help(self, runner):
        """Test find command help."""
        result = runner.invoke(cli, ["literature", "find", "--help"])
        assert result.exit_code == 0
        assert "Find papers matching QUERY" in result.output
        assert "--timeout" in result.output
        assert "-o" in result.output or "--output" in result.output

    def test_find_missing_query(self, runner):
        """Test find command without query argument."""
        result = runner.invoke(cli, ["literature", "find"])
        assert result.exit_code != 0
        assert "Missing argument" in result.output

    def test_find_success_stdout(self, runner):
        """Test successful find with stdout output."""
        mock_result = {
            "query": "test query",
            "widget_id": "test-widget-123",
            "status": "completed",
            "paper_count": 5,
            "widget": {
                "results": [
                    {
                        "corpusId": 123,
                        "title": "Test Paper",
                        "relevanceScore": 0.9,
                        "authors": [],
                    }
                ]
            },
        }

        with patch("asta.literature.find.AstaPaperFinder") as MockFinder:
            mock_instance = MagicMock()
            mock_instance.find_papers.return_value = mock_result
            MockFinder.return_value = mock_instance

            result = runner.invoke(cli, ["literature", "find", "test query", "-o", "-"])

        assert result.exit_code == 0
        output_data = json.loads(result.output)
        assert output_data["query"] == "test query"
        assert len(output_data["results"]) == 1
        assert output_data["results"][0]["corpusId"] == 123

    def test_find_success_file_output(self, runner, tmp_path):
        """Test successful find with file output."""
        output_file = tmp_path / "results.json"
        mock_result = {
            "query": "test query",
            "widget_id": "test-widget-123",
            "status": "completed",
            "paper_count": 5,
            "file_path": str(output_file),
            "widget": {
                "results": [
                    {
                        "corpusId": 123,
                        "title": "Test Paper",
                        "relevanceScore": 0.9,
                        "authors": [],
                    },
                    {
                        "corpusId": 456,
                        "title": "Another Paper",
                        "relevanceScore": 0.8,
                        "authors": [],
                    },
                ]
            },
        }

        with patch("asta.literature.find.AstaPaperFinder") as MockFinder:
            mock_instance = MagicMock()
            mock_instance.find_papers.return_value = mock_result
            MockFinder.return_value = mock_instance

            result = runner.invoke(
                cli, ["literature", "find", "test query", "-o", str(output_file)]
            )

        assert result.exit_code == 0
        assert "Search completed successfully!" in result.output
        assert "Papers found: 2" in result.output
        assert str(output_file) in result.output

    def test_find_timeout_error(self, runner):
        """Test find command with timeout error."""
        with patch("asta.literature.find.AstaPaperFinder") as MockFinder:
            mock_instance = MagicMock()
            mock_instance.find_papers.side_effect = TimeoutError(
                "Timeout after 300 seconds"
            )
            MockFinder.return_value = mock_instance

            result = runner.invoke(cli, ["literature", "find", "test query"])

        assert result.exit_code == 2
        assert "Timeout" in result.output

    def test_find_general_error(self, runner):
        """Test find command with general error."""
        with patch("asta.literature.find.AstaPaperFinder") as MockFinder:
            mock_instance = MagicMock()
            mock_instance.find_papers.side_effect = Exception("API error")
            MockFinder.return_value = mock_instance

            result = runner.invoke(cli, ["literature", "find", "test query"])

        assert result.exit_code == 1
        assert "Error" in result.output

    def test_find_custom_timeout(self, runner):
        """Test find command with custom timeout."""
        mock_result = {
            "query": "test query",
            "widget_id": "test-widget-123",
            "status": "completed",
            "paper_count": 3,
            "widget": {
                "results": [
                    {
                        "corpusId": 123,
                        "title": "Test Paper",
                        "relevanceScore": 0.9,
                        "authors": [],
                    }
                ]
            },
        }

        with patch("asta.literature.find.AstaPaperFinder") as MockFinder:
            mock_instance = MagicMock()
            mock_instance.find_papers.return_value = mock_result
            MockFinder.return_value = mock_instance

            result = runner.invoke(
                cli, ["literature", "find", "test query", "--timeout", "60"]
            )

        assert result.exit_code == 0
        mock_instance.find_papers.assert_called_once_with(
            "test query", timeout=60, save_to_file=None
        )


class TestPassthroughUtility:
    """Test generic passthrough utility functions."""

    def test_ensure_tool_installed_already_exists(self):
        """Test ensure_tool_installed when tool is already on PATH."""
        from asta.utils.passthrough import ensure_tool_installed

        with patch("asta.utils.passthrough.shutil.which") as mock_which:
            mock_which.return_value = "/usr/local/bin/test-tool"
            result = ensure_tool_installed(
                "test-tool", "git+https://example.com/repo.git", "v1.0.0"
            )

        assert result is not None
        assert str(result) == "/usr/local/bin/test-tool"

    def test_ensure_tool_installed_installation_needed(self):
        """Test ensure_tool_installed when installation is needed."""
        from asta.utils.passthrough import ensure_tool_installed

        with patch("asta.utils.passthrough.shutil.which") as mock_which:
            # First call returns None (not found), second returns path (after install)
            mock_which.side_effect = [None, "/usr/local/bin/test-tool"]

            with patch("asta.utils.passthrough.subprocess.run") as mock_run:
                mock_run.return_value = MagicMock(returncode=0)

                result = ensure_tool_installed(
                    "test-tool",
                    "git+https://example.com/repo.git",
                    "v1.0.0",
                    friendly_name="Test Tool",
                )

        assert result is not None
        mock_run.assert_called_once()


class TestDocumentsCommand:
    """Test 'asta documents' passthrough command."""

    def test_documents_version_constant(self):
        """Test that ASTA_DOCUMENTS_VERSION is properly defined."""
        from asta.documents.passthrough import ASTA_DOCUMENTS_VERSION

        # Should be a non-empty string starting with 'v'
        assert isinstance(ASTA_DOCUMENTS_VERSION, str)
        assert len(ASTA_DOCUMENTS_VERSION) > 0
        assert ASTA_DOCUMENTS_VERSION.startswith("v")
        # Should look like a version tag (v0.1.0 format)
        assert ASTA_DOCUMENTS_VERSION.count(".") >= 1

    def test_documents_help_requires_installation(self, runner):
        """Test documents command behavior when asta-documents not installed."""
        with patch("asta.utils.passthrough.shutil.which") as mock_which:
            mock_which.return_value = None

            with patch("asta.utils.passthrough.subprocess.run") as mock_subprocess:
                # Mock installation failure
                mock_subprocess.side_effect = FileNotFoundError("uv not found")

                result = runner.invoke(cli, ["documents", "--help"])

        assert result.exit_code != 0
        assert "uv" in result.output.lower()

    def test_documents_passthrough_when_installed(self, runner, tmp_path):
        """Test documents command passes through when asta-documents is installed."""
        # Create a fake asta-documents executable
        fake_exe = tmp_path / "asta-documents"
        fake_exe.write_text("#!/bin/bash\necho 'passthrough success'")
        fake_exe.chmod(0o755)

        with patch("asta.utils.passthrough.shutil.which") as mock_which:
            mock_which.return_value = str(fake_exe)

            with patch("asta.utils.passthrough.subprocess.run") as mock_subprocess:
                mock_subprocess.return_value = MagicMock(
                    returncode=0, stdout="passthrough success\n", stderr=""
                )

                result = runner.invoke(cli, ["documents", "list"])

        assert result.exit_code == 0
        assert "passthrough success" in result.output


class TestExperimentCommand:
    """Test 'asta experiment' passthrough command."""

    def test_experiment_version_constant(self):
        """Test that PANDA_VERSION is properly defined."""
        from asta.experiment.passthrough import PANDA_VERSION

        # Should be a non-empty string
        assert isinstance(PANDA_VERSION, str)
        assert len(PANDA_VERSION) > 0

    def test_experiment_help_requires_installation(self, runner):
        """Test experiment command behavior when panda not installed."""
        with patch("asta.utils.passthrough.shutil.which") as mock_which:
            mock_which.return_value = None

            with patch("asta.utils.passthrough.subprocess.run") as mock_subprocess:
                # Mock installation failure
                mock_subprocess.side_effect = FileNotFoundError("uv not found")

                result = runner.invoke(cli, ["experiment", "--help"])

        assert result.exit_code != 0
        assert "uv" in result.output.lower()

    def test_experiment_passthrough_when_installed(self, runner, tmp_path):
        """Test experiment command passes through when panda is installed."""
        # Create a fake panda executable
        fake_exe = tmp_path / "panda"
        fake_exe.write_text("#!/bin/bash\necho 'panda running'")
        fake_exe.chmod(0o755)

        with patch("asta.utils.passthrough.shutil.which") as mock_which:
            mock_which.return_value = str(fake_exe)

            with patch("asta.utils.passthrough.subprocess.run") as mock_subprocess:
                mock_subprocess.return_value = MagicMock(
                    returncode=0, stdout="panda running\n", stderr=""
                )

                result = runner.invoke(cli, ["experiment", "--task", "test"])

        assert result.exit_code == 0
        assert "running" in result.output


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
