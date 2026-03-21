"""Tests for the Asta CLI."""

import json
from pathlib import Path
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

    def test_cli_commands_work(self, runner):
        """Test that basic CLI commands execute successfully."""
        # Just verify the CLI is functional
        assert runner.invoke(cli, ["--version"]).exit_code == 0
        assert runner.invoke(cli, ["--help"]).exit_code == 0


class TestFindCommand:
    """Test 'asta literature find' command."""

    def test_find_missing_query(self, runner):
        """Test find command without query argument."""
        result = runner.invoke(cli, ["literature", "find"])
        assert result.exit_code != 0

    def test_find_success_file_output(self, runner, tmp_path):
        """Test successful find writes to default location."""
        mock_result = {
            "query": "test query",
            "widget_id": "test-widget-123",
            "status": "completed",
            "paper_count": 2,
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

            output_file = tmp_path / "results.json"
            result = runner.invoke(
                cli, ["literature", "find", "test query", "-o", str(output_file)]
            )

        assert result.exit_code == 0

        # Verify file was created at specified location
        assert output_file.exists()

        # Verify file contents
        with open(output_file) as f:
            data = json.load(f)

        assert data["query"] == "test query"
        assert len(data["results"]) == 2
        assert data["results"][0]["corpusId"] == 123
        assert data["results"][1]["corpusId"] == 456

    def test_find_timeout_error(self, runner, tmp_path):
        """Test find command with timeout error."""
        with patch("asta.literature.find.AstaPaperFinder") as MockFinder:
            mock_instance = MagicMock()
            mock_instance.find_papers.side_effect = TimeoutError(
                "Timeout after 300 seconds"
            )
            MockFinder.return_value = mock_instance

            output_file = tmp_path / "results.json"
            result = runner.invoke(
                cli, ["literature", "find", "test query", "-o", str(output_file)]
            )

        assert result.exit_code == 2

    def test_find_general_error(self, runner, tmp_path):
        """Test find command with general error."""
        with patch("asta.literature.find.AstaPaperFinder") as MockFinder:
            mock_instance = MagicMock()
            mock_instance.find_papers.side_effect = Exception("API error")
            MockFinder.return_value = mock_instance

            output_file = tmp_path / "results.json"
            result = runner.invoke(
                cli, ["literature", "find", "test query", "-o", str(output_file)]
            )

        assert result.exit_code == 1

    def test_find_custom_timeout(self, runner, tmp_path):
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

            output_file = tmp_path / "results.json"
            result = runner.invoke(
                cli,
                [
                    "literature",
                    "find",
                    "test query",
                    "-o",
                    str(output_file),
                    "--timeout",
                    "60",
                ],
            )

        assert result.exit_code == 0
        mock_instance.find_papers.assert_called_once_with(
            "test query", timeout=60, save_to_file=None, operation_mode="infer"
        )

    def test_find_with_mode_option(self, runner, tmp_path):
        """Test find command with different operation modes."""
        mock_result = {
            "query": "test query",
            "status": "completed",
            "paper_count": 1,
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

            output_file = tmp_path / "results.json"
            # Test fast mode
            result = runner.invoke(
                cli,
                [
                    "literature",
                    "find",
                    "test query",
                    "-o",
                    str(output_file),
                    "--mode",
                    "fast",
                ],
            )

        assert result.exit_code == 0
        mock_instance.find_papers.assert_called_with(
            "test query", timeout=300, save_to_file=None, operation_mode="fast"
        )


class TestReportCommand:
    """Test 'asta literature report' command."""

    RESULTS_JSON = {
        "query": "transformers for NLP",
        "results": [
            {
                "corpus_id": 111,
                "title": "Attention Is All You Need",
                "abstract": "We propose a new network architecture, the Transformer.",
                "year": 2017,
                "authors": [{"name": "Vaswani, A.", "authorId": "1"}],
                "relevance_score": 0.95,
                "snippets": [{"text": "The Transformer follows an encoder-decoder structure."}],
            },
            {
                "corpus_id": 222,
                "title": "BERT: Pre-training of Deep Bidirectional Transformers",
                "abstract": "We introduce BERT.",
                "year": 2019,
                "authors": [{"name": "Devlin, J.", "authorId": "2"}],
                "relevance_score": 0.90,
                "snippets": [],
            },
        ],
    }

    API_RESPONSE = {
        "report_title": "Transformers for NLP",
        "sections": [
            {"title": "Introduction", "text": "Transformers have revolutionized NLP."},
            {"title": "Key Works", "text": "Vaswani et al. introduced the Transformer."},
        ],
        "report_id": "report-abc-123",
        "cost": 0.01,
    }

    def test_report_missing_input(self, runner, tmp_path):
        """Test report command fails without --input."""
        output_file = tmp_path / "report.md"
        result = runner.invoke(cli, ["literature", "report", "-o", str(output_file)])
        assert result.exit_code != 0

    def test_report_missing_output(self, runner, tmp_path):
        """Test report command fails without --output."""
        input_file = tmp_path / "results.json"
        input_file.write_text(json.dumps(self.RESULTS_JSON))
        result = runner.invoke(cli, ["literature", "report", "-i", str(input_file)])
        assert result.exit_code != 0

    def test_report_success(self, runner, tmp_path):
        """Test successful report generation writes markdown file."""
        input_file = tmp_path / "results.json"
        input_file.write_text(json.dumps(self.RESULTS_JSON))
        output_file = tmp_path / "report.md"

        with patch("asta.literature.report.NoraReportClient") as MockClient:
            mock_instance = MagicMock()
            mock_instance.generate_report.return_value = self.API_RESPONSE
            MockClient.return_value = mock_instance

            result = runner.invoke(
                cli,
                ["literature", "report", "-i", str(input_file), "-o", str(output_file)],
            )

        assert result.exit_code == 0, result.output
        assert output_file.exists()
        content = output_file.read_text()
        assert "# Transformers for NLP" in content
        assert "## Introduction" in content
        assert "Transformers have revolutionized NLP." in content

    def test_report_passes_query_from_results(self, runner, tmp_path):
        """Test that the query from the results file is passed to the client."""
        input_file = tmp_path / "results.json"
        input_file.write_text(json.dumps(self.RESULTS_JSON))
        output_file = tmp_path / "report.md"

        with patch("asta.literature.report.NoraReportClient") as MockClient:
            mock_instance = MagicMock()
            mock_instance.generate_report.return_value = self.API_RESPONSE
            MockClient.return_value = mock_instance

            runner.invoke(
                cli,
                ["literature", "report", "-i", str(input_file), "-o", str(output_file)],
            )

            mock_instance.generate_report.assert_called_once()
            call_kwargs = mock_instance.generate_report.call_args[1]
            assert call_kwargs["query"] == "transformers for NLP"

    def test_report_query_override(self, runner, tmp_path):
        """Test --query overrides the query from the results file."""
        input_file = tmp_path / "results.json"
        input_file.write_text(json.dumps(self.RESULTS_JSON))
        output_file = tmp_path / "report.md"

        with patch("asta.literature.report.NoraReportClient") as MockClient:
            mock_instance = MagicMock()
            mock_instance.generate_report.return_value = self.API_RESPONSE
            MockClient.return_value = mock_instance

            runner.invoke(
                cli,
                [
                    "literature",
                    "report",
                    "-i",
                    str(input_file),
                    "-o",
                    str(output_file),
                    "--query",
                    "custom query",
                ],
            )

            call_kwargs = mock_instance.generate_report.call_args[1]
            assert call_kwargs["query"] == "custom query"

    def test_report_max_papers_option(self, runner, tmp_path):
        """Test --max-papers limits the number of documents sent."""
        input_file = tmp_path / "results.json"
        input_file.write_text(json.dumps(self.RESULTS_JSON))
        output_file = tmp_path / "report.md"

        with patch("asta.literature.report.NoraReportClient") as MockClient:
            mock_instance = MagicMock()
            mock_instance.generate_report.return_value = self.API_RESPONSE
            MockClient.return_value = mock_instance

            runner.invoke(
                cli,
                [
                    "literature",
                    "report",
                    "-i",
                    str(input_file),
                    "-o",
                    str(output_file),
                    "--max-papers",
                    "1",
                ],
            )

            call_kwargs = mock_instance.generate_report.call_args[1]
            assert len(call_kwargs["documents"]) == 1
            # Should be the highest-relevance paper
            assert call_kwargs["documents"][0]["corpus_id"] == "111"

    def test_report_api_error(self, runner, tmp_path):
        """Test report command exits with code 1 on API error."""
        input_file = tmp_path / "results.json"
        input_file.write_text(json.dumps(self.RESULTS_JSON))
        output_file = tmp_path / "report.md"

        with patch("asta.literature.report.NoraReportClient") as MockClient:
            mock_instance = MagicMock()
            mock_instance.generate_report.side_effect = Exception("API error")
            MockClient.return_value = mock_instance

            result = runner.invoke(
                cli,
                ["literature", "report", "-i", str(input_file), "-o", str(output_file)],
            )

        assert result.exit_code == 1

    def test_report_config(self):
        """Test that the report API is configured in asta.conf."""
        from asta.utils.config import get_api_config

        config = get_api_config("report")
        assert "base_url" in config
        assert "/api/corpus-qa" in config["base_url"]


class TestPassthroughUtility:
    """Test generic passthrough utility functions."""

    def test_get_installed_version(self):
        """Test extracting version from tool --version output."""
        from asta.utils.passthrough import get_installed_version

        with patch("asta.utils.passthrough.subprocess.run") as mock_run:
            # Test various version output formats
            test_cases = [
                ("panda 0.1.0\n", "0.1.0"),
                ("v1.2.3\n", "v1.2.3"),
                ("tool version v2.3.4\n", "v2.3.4"),
                ("1.0.0\n", "1.0.0"),
            ]

            for output, expected in test_cases:
                mock_run.return_value = MagicMock(returncode=0, stdout=output)
                version = get_installed_version(Path("/usr/local/bin/test-tool"))
                assert version == expected, f"Failed for output: {output}"

    def test_parse_semver(self):
        """Test semantic version parsing."""
        from asta.utils.passthrough import parse_semver

        # Valid versions
        assert parse_semver("1.2.3") == (1, 2, 3)
        assert parse_semver("v1.2.3") == (1, 2, 3)
        assert parse_semver("0.1.0") == (0, 1, 0)
        assert parse_semver("10.20.30") == (10, 20, 30)

        # Invalid versions
        assert parse_semver("1.2") is None
        assert parse_semver("1") is None
        assert parse_semver("main") is None
        assert parse_semver("") is None
        assert parse_semver(None) is None

    def test_validate_semver(self):
        """Test semantic version validation."""
        from asta.utils.passthrough import validate_semver

        # Valid versions
        assert validate_semver("1.2.3") is True
        assert validate_semver("v1.2.3") is True
        assert validate_semver("0.1.0") is True

        # Invalid versions
        assert validate_semver("1.2") is False
        assert validate_semver("main") is False
        assert validate_semver("") is False

    def test_version_meets_minimum(self):
        """Test minimum version checking."""
        from asta.utils.passthrough import version_meets_minimum

        # Same version
        assert version_meets_minimum("1.0.0", "1.0.0") is True
        assert version_meets_minimum("v1.0.0", "1.0.0") is True

        # Newer versions (should pass)
        assert version_meets_minimum("1.0.1", "1.0.0") is True
        assert version_meets_minimum("1.1.0", "1.0.0") is True
        assert version_meets_minimum("2.0.0", "1.0.0") is True
        assert version_meets_minimum("v2.0.0", "1.0.0") is True

        # Older versions (should fail)
        assert version_meets_minimum("0.9.0", "1.0.0") is False
        assert version_meets_minimum("1.0.0", "1.0.1") is False
        assert version_meets_minimum("1.0.0", "1.1.0") is False

    def test_ensure_tool_installed_meets_minimum(self):
        """Test ensure_tool_installed when installed version meets minimum."""
        from asta.utils.passthrough import ensure_tool_installed

        with patch("asta.utils.passthrough.shutil.which") as mock_which:
            mock_which.return_value = "/usr/local/bin/test-tool"

            with patch("asta.utils.passthrough.get_installed_version") as mock_version:
                # Installed version 1.2.0 meets minimum 1.0.0
                mock_version.return_value = "1.2.0"

                result = ensure_tool_installed(
                    "test-tool", "git", "git+https://example.com/repo.git", "1.0.0"
                )

        assert result is not None
        assert str(result) == "/usr/local/bin/test-tool"

    def test_ensure_tool_installed_below_minimum(self):
        """Test ensure_tool_installed when version is below minimum."""
        from asta.utils.passthrough import ensure_tool_installed

        with patch("asta.utils.passthrough.shutil.which") as mock_which:
            # First call finds old version, second call after reinstall
            mock_which.side_effect = [
                "/usr/local/bin/test-tool",
                "/usr/local/bin/test-tool",
            ]

            with patch("asta.utils.passthrough.get_installed_version") as mock_version:
                mock_version.return_value = "0.9.0"  # Below minimum

                with patch("asta.utils.passthrough.install_tool") as mock_install:
                    mock_install.return_value = True

                    result = ensure_tool_installed(
                        "test-tool", "git", "git+https://example.com/repo.git", "1.0.0"
                    )

        assert result is not None
        mock_install.assert_called_once()

    def test_ensure_tool_installed_invalid_minimum_version(self):
        """Test ensure_tool_installed with invalid minimum_version format."""
        from asta.utils.passthrough import ensure_tool_installed

        with patch("asta.utils.passthrough.shutil.which") as mock_which:
            mock_which.return_value = "/usr/local/bin/test-tool"

            # Should raise ValueError for invalid minimum_version
            import pytest

            with pytest.raises(ValueError):
                ensure_tool_installed(
                    "test-tool", "git", "git+https://example.com/repo.git", "main"
                )

    def test_ensure_tool_installed_invalid_install_type(self):
        """Test ensure_tool_installed with invalid install_type."""
        from asta.utils.passthrough import ensure_tool_installed

        with patch("asta.utils.passthrough.shutil.which") as mock_which:
            mock_which.return_value = None

            with patch("asta.utils.passthrough.install_tool") as mock_install:
                # install_tool should raise ValueError for invalid type
                mock_install.side_effect = ValueError("Invalid install_type")

                import pytest

                with pytest.raises(ValueError):
                    ensure_tool_installed("test-tool", "invalid", "source", "1.0.0")

    def test_ensure_tool_installed_installation_needed(self):
        """Test ensure_tool_installed when installation is needed."""
        from asta.utils.passthrough import ensure_tool_installed

        with patch("asta.utils.passthrough.shutil.which") as mock_which:
            # First call returns None (not found), second returns path (after install)
            mock_which.side_effect = [None, "/usr/local/bin/test-tool"]

            with patch("asta.utils.passthrough.install_tool") as mock_install:
                mock_install.return_value = True

                result = ensure_tool_installed(
                    "test-tool",
                    "git",
                    "git+https://example.com/repo.git",
                    "1.0.0",
                )

        assert result is not None
        mock_install.assert_called_once()

    def test_install_tool_pypi(self):
        """Test install_tool with PyPI source."""
        from asta.utils.passthrough import install_tool

        with patch("asta.utils.passthrough.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0)

            result = install_tool("test-tool", "pypi", "test-package", "1.0.0")

            assert result is True
            # Verify the command includes >=version for PyPI
            mock_run.assert_called_once()
            call_args = mock_run.call_args[0][0]
            assert "test-package>=1.0.0" in call_args

    def test_install_tool_git(self):
        """Test install_tool with Git source."""
        from asta.utils.passthrough import install_tool

        with patch("asta.utils.passthrough.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0)

            result = install_tool(
                "test-tool", "git", "git+https://github.com/user/repo", "1.0.0"
            )

            assert result is True
            # Verify the command includes @v{version} for git
            mock_run.assert_called_once()
            call_args = mock_run.call_args[0][0]
            assert "git+https://github.com/user/repo@v1.0.0" in call_args

    def test_install_tool_local(self):
        """Test install_tool with local filesystem source."""
        from asta.utils.passthrough import install_tool

        with patch("asta.utils.passthrough.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0)

            result = install_tool("test-tool", "local", "~/dev/my-package", "1.0.0")

            assert result is True
            # Verify the path is expanded
            mock_run.assert_called_once()
            call_args = mock_run.call_args[0][0]
            # Should have expanded ~ to home directory
            assert "~" not in " ".join(call_args)

    def test_install_tool_invalid_type(self):
        """Test install_tool with invalid install type."""
        import pytest

        from asta.utils.passthrough import install_tool

        with pytest.raises(ValueError):
            install_tool("test-tool", "invalid", "source", "1.0.0")


class TestDocumentsCommand:
    """Test 'asta documents' passthrough command."""

    def test_documents_config(self):
        """Test that documents configuration is properly defined."""
        from asta.utils.config import get_config
        from asta.utils.passthrough import validate_semver

        config = get_config()["passthrough"]["documents"]

        # Should have required fields
        assert config["tool_name"] == "asta-documents"
        assert config["install_type"] == "pypi"
        assert config["install_source"] == "asta-resource-repository"
        assert config["minimum_version"] == "0.3.0"
        assert validate_semver(config["minimum_version"])
        assert config["command_name"] == "documents"

    def test_documents_help_requires_installation(self, runner):
        """Test documents command behavior when asta-documents not installed."""
        with patch("asta.utils.passthrough.shutil.which") as mock_which:
            mock_which.return_value = None

            with patch("asta.utils.passthrough.subprocess.run") as mock_subprocess:
                # Mock installation failure
                mock_subprocess.side_effect = FileNotFoundError("uv not found")

                result = runner.invoke(cli, ["documents", "--help"])

        assert result.exit_code != 0


class TestExperimentCommand:
    """Test 'asta experiment' passthrough command."""

    def test_experiment_config(self):
        """Test that experiment configuration is properly defined."""
        from asta.utils.config import get_config
        from asta.utils.passthrough import validate_semver

        config = get_config()["passthrough"]["experiment"]

        # Should have required fields
        assert config["tool_name"] == "panda"
        assert "install_type" in config
        assert config["install_type"] in ("pypi", "git", "local")
        assert "minimum_version" in config
        assert validate_semver(config["minimum_version"])
        assert "install_source" in config
        assert config["command_name"] == "experiment"

    def test_experiment_help_requires_installation(self, runner):
        """Test experiment command behavior when panda not installed."""
        with patch("asta.utils.passthrough.shutil.which") as mock_which:
            mock_which.return_value = None

            with patch("asta.utils.passthrough.subprocess.run") as mock_subprocess:
                # Mock installation failure
                mock_subprocess.side_effect = FileNotFoundError("uv not found")

                result = runner.invoke(cli, ["experiment", "--help"])

        assert result.exit_code != 0


class TestPDFExtractionCommand:
    """Test 'asta pdf-extraction' passthrough command."""

    def test_pdf_extraction_config(self):
        """Test that pdf-extraction configuration is properly defined."""
        from asta.utils.config import get_passthrough_config
        from asta.utils.passthrough import validate_semver

        config = get_passthrough_config("pdf-extraction")

        # Should have required fields
        assert config["tool_name"] == "olmocr"
        assert "install_type" in config
        assert config["install_type"] in ("pypi", "git", "local")
        assert "minimum_version" in config
        assert validate_semver(config["minimum_version"])
        assert "install_source" in config
        assert config["command_name"] == "pdf-extraction"

    def test_pdf_extraction_help_requires_installation(self, runner):
        """Test pdf-extraction command behavior when olmocr not installed."""
        with patch("asta.utils.passthrough.shutil.which") as mock_which:
            mock_which.return_value = None

            with patch("asta.utils.passthrough.subprocess.run") as mock_subprocess:
                # Mock installation failure
                mock_subprocess.side_effect = FileNotFoundError("uv not found")

                result = runner.invoke(cli, ["pdf-extraction", "--help"])

        assert result.exit_code != 0


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
