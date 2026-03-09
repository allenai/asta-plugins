"""Tests for PDF text extraction commands."""

from unittest.mock import MagicMock, Mock, patch

import pytest
from click.testing import CliRunner

from asta.cli import cli


@pytest.fixture
def runner():
    """Provide a Click CLI test runner."""
    return CliRunner()


@pytest.fixture
def mock_pdf_doc():
    """Create a mock PyMuPDF document."""
    doc = MagicMock()
    doc.__len__ = Mock(return_value=3)  # 3 pages

    # Mock pages
    page1 = MagicMock()
    page1.get_text.return_value = "Page 1 content"
    page2 = MagicMock()
    page2.get_text.return_value = "Page 2 content"
    page3 = MagicMock()
    page3.get_text.return_value = "Page 3 content"

    doc.__getitem__ = Mock(side_effect=lambda i: [page1, page2, page3][i])
    return doc


class TestPDFToTextCommand:
    """Test 'asta pdf to-text' command."""

    def test_to_text_missing_file(self, runner):
        """Test to-text command with non-existent file."""
        result = runner.invoke(cli, ["pdf", "to-text", "nonexistent.pdf"])
        assert result.exit_code != 0
        assert (
            "does not exist" in result.output.lower()
            or "error" in result.output.lower()
        )

    def test_to_text_help(self, runner):
        """Test to-text command help."""
        result = runner.invoke(cli, ["pdf", "to-text", "--help"])
        assert result.exit_code == 0
        assert "Extract text from PDF" in result.output
        assert "--format" in result.output
        assert "--output" in result.output

    @patch("asta.pdf.to_text.pymupdf.open")
    @patch("asta.pdf.to_text.pymupdf4llm.to_markdown")
    def test_to_text_markdown_stdout(
        self, mock_to_markdown, mock_open, runner, tmp_path, mock_pdf_doc
    ):
        """Test extracting to markdown and printing to stdout."""
        # Create a temporary PDF file
        pdf_file = tmp_path / "test.pdf"
        pdf_file.write_bytes(b"%PDF-1.4 fake pdf")

        # Setup mocks
        mock_open.return_value = mock_pdf_doc
        mock_to_markdown.return_value = "# Test Document\n\nTest content"

        # Run command
        result = runner.invoke(cli, ["pdf", "to-text", str(pdf_file)])

        # Verify
        assert result.exit_code == 0
        assert "# Test Document" in result.output
        mock_open.assert_called_once()
        mock_to_markdown.assert_called_once()

    @patch("asta.pdf.to_text.pymupdf.open")
    @patch("asta.pdf.to_text.pymupdf4llm.to_markdown")
    def test_to_text_json_format(
        self, mock_to_markdown, mock_open, runner, tmp_path, mock_pdf_doc
    ):
        """Test extracting to JSON format."""
        pdf_file = tmp_path / "test.pdf"
        pdf_file.write_bytes(b"%PDF-1.4 fake pdf")

        # Setup mocks - return list for page chunks
        mock_open.return_value = mock_pdf_doc
        mock_to_markdown.return_value = [
            {"page": 1, "content": "Page 1"},
            {"page": 2, "content": "Page 2"},
        ]

        # Run command
        result = runner.invoke(
            cli, ["pdf", "to-text", str(pdf_file), "--format", "json"]
        )

        # Verify
        assert result.exit_code == 0
        assert '"page":' in result.output or '"content":' in result.output

    @patch("asta.pdf.to_text.pymupdf.open")
    @patch("asta.pdf.to_text.pymupdf4llm.to_markdown")
    def test_to_text_output_file(
        self, mock_to_markdown, mock_open, runner, tmp_path, mock_pdf_doc
    ):
        """Test extracting to output file."""
        pdf_file = tmp_path / "test.pdf"
        pdf_file.write_bytes(b"%PDF-1.4 fake pdf")
        output_file = tmp_path / "output.md"

        # Setup mocks
        mock_open.return_value = mock_pdf_doc
        mock_to_markdown.return_value = "# Test Document\n\nTest content"

        # Run command
        result = runner.invoke(
            cli, ["pdf", "to-text", str(pdf_file), "-o", str(output_file)]
        )

        # Verify
        assert result.exit_code == 0
        assert output_file.exists()
        assert "# Test Document" in output_file.read_text()
        assert "Text extracted to:" in result.output

    @patch("asta.pdf.to_text.pymupdf.open")
    def test_to_text_plain_text_format(self, mock_open, runner, tmp_path, mock_pdf_doc):
        """Test extracting to plain text format."""
        pdf_file = tmp_path / "test.pdf"
        pdf_file.write_bytes(b"%PDF-1.4 fake pdf")

        # Setup mocks
        mock_open.return_value = mock_pdf_doc

        # Run command
        result = runner.invoke(
            cli, ["pdf", "to-text", str(pdf_file), "--format", "text"]
        )

        # Verify
        assert result.exit_code == 0
        assert "Page 1 content" in result.output
        assert "Page 2 content" in result.output
        assert "Page 3 content" in result.output

    @patch("asta.pdf.to_text.pymupdf.open")
    @patch("asta.pdf.to_text.pymupdf4llm.to_markdown")
    def test_to_text_page_range(
        self, mock_to_markdown, mock_open, runner, tmp_path, mock_pdf_doc
    ):
        """Test extracting specific page range."""
        pdf_file = tmp_path / "test.pdf"
        pdf_file.write_bytes(b"%PDF-1.4 fake pdf")

        # Setup mocks
        mock_open.return_value = mock_pdf_doc
        mock_to_markdown.return_value = "# Pages 1-2"

        # Run command
        result = runner.invoke(cli, ["pdf", "to-text", str(pdf_file), "--pages", "1-2"])

        # Verify
        assert result.exit_code == 0
        # Check that page_list parameter was passed correctly
        call_args = mock_to_markdown.call_args
        assert call_args is not None
        assert call_args.kwargs["pages"] == [0, 1]  # 0-indexed

    @patch("asta.pdf.to_text.pymupdf.open")
    @patch("asta.pdf.to_text.pymupdf4llm.to_markdown")
    def test_to_text_specific_pages(
        self, mock_to_markdown, mock_open, runner, tmp_path, mock_pdf_doc
    ):
        """Test extracting specific pages."""
        pdf_file = tmp_path / "test.pdf"
        pdf_file.write_bytes(b"%PDF-1.4 fake pdf")

        # Setup mocks
        mock_open.return_value = mock_pdf_doc
        mock_to_markdown.return_value = "# Pages 1 and 3"

        # Run command
        result = runner.invoke(cli, ["pdf", "to-text", str(pdf_file), "--pages", "1,3"])

        # Verify
        assert result.exit_code == 0
        # Check that page_list parameter was passed correctly
        call_args = mock_to_markdown.call_args
        assert call_args is not None
        assert call_args.kwargs["pages"] == [0, 2]  # 0-indexed

    @patch("asta.pdf.to_text.pymupdf.open")
    @patch("asta.pdf.to_text.pymupdf4llm.to_markdown")
    def test_to_text_no_page_chunks(
        self, mock_to_markdown, mock_open, runner, tmp_path, mock_pdf_doc
    ):
        """Test extracting without page chunks."""
        pdf_file = tmp_path / "test.pdf"
        pdf_file.write_bytes(b"%PDF-1.4 fake pdf")

        # Setup mocks
        mock_open.return_value = mock_pdf_doc
        mock_to_markdown.return_value = "Continuous text"

        # Run command
        result = runner.invoke(
            cli, ["pdf", "to-text", str(pdf_file), "--no-page-chunks"]
        )

        # Verify
        assert result.exit_code == 0
        call_args = mock_to_markdown.call_args
        assert call_args is not None
        assert call_args.kwargs["page_chunks"] is False

    @patch("asta.pdf.to_text.pymupdf.open")
    def test_to_text_error_handling(self, mock_open, runner, tmp_path):
        """Test error handling when PDF processing fails."""
        pdf_file = tmp_path / "test.pdf"
        pdf_file.write_bytes(b"%PDF-1.4 fake pdf")

        # Setup mock to raise an exception
        mock_open.side_effect = Exception("PDF processing error")

        # Run command
        result = runner.invoke(cli, ["pdf", "to-text", str(pdf_file)])

        # Verify
        assert result.exit_code != 0
        assert "Failed to extract text from PDF" in result.output


class TestPageRangeParsing:
    """Test page range parsing utility function."""

    def test_parse_page_range_single(self):
        """Test parsing single page."""
        from asta.pdf.to_text import _parse_page_range

        assert _parse_page_range("1") == [0]
        assert _parse_page_range("5") == [4]

    def test_parse_page_range_range(self):
        """Test parsing page range."""
        from asta.pdf.to_text import _parse_page_range

        assert _parse_page_range("1-3") == [0, 1, 2]
        assert _parse_page_range("5-7") == [4, 5, 6]

    def test_parse_page_range_multiple(self):
        """Test parsing multiple pages."""
        from asta.pdf.to_text import _parse_page_range

        assert _parse_page_range("1,3,5") == [0, 2, 4]

    def test_parse_page_range_mixed(self):
        """Test parsing mixed range and individual pages."""
        from asta.pdf.to_text import _parse_page_range

        result = _parse_page_range("1-3,5,7-9")
        assert result == [0, 1, 2, 4, 6, 7, 8]


class TestBatchExtractCommand:
    """Test 'asta pdf batch-extract' command."""

    def test_batch_extract_help(self, runner):
        """Test batch-extract command help."""
        result = runner.invoke(cli, ["pdf", "batch-extract", "--help"])
        assert result.exit_code == 0
        assert "Extract text from multiple PDF files" in result.output
        assert "--output-dir" in result.output
        assert "--workers" in result.output

    def test_batch_extract_missing_args(self, runner):
        """Test batch-extract without required arguments."""
        result = runner.invoke(cli, ["pdf", "batch-extract"])
        assert result.exit_code != 0

    @patch("asta.pdf.batch_extract.Pool")
    @patch("asta.pdf.batch_extract.cpu_count")
    def test_batch_extract_success(self, mock_cpu_count, mock_pool, runner, tmp_path):
        """Test successful batch extraction."""
        # Create fake PDF files
        pdf1 = tmp_path / "test1.pdf"
        pdf2 = tmp_path / "test2.pdf"
        pdf1.write_bytes(b"%PDF-1.4 fake")
        pdf2.write_bytes(b"%PDF-1.4 fake")

        output_dir = tmp_path / "output"

        # Mock CPU count
        mock_cpu_count.return_value = 4

        # Mock the pool and its map method
        mock_pool_instance = MagicMock()
        mock_pool.return_value.__enter__.return_value = mock_pool_instance
        mock_pool_instance.map.return_value = [
            {
                "success": True,
                "input": str(pdf1),
                "output": str(output_dir / "test1.md"),
            },
            {
                "success": True,
                "input": str(pdf2),
                "output": str(output_dir / "test2.md"),
            },
        ]

        # Run command
        result = runner.invoke(
            cli, ["pdf", "batch-extract", str(pdf1), str(pdf2), "-o", str(output_dir)]
        )

        # Verify
        assert result.exit_code == 0
        assert "Processing 2 PDFs" in result.output
        assert "Successfully processed 2 PDFs" in result.output
        mock_pool_instance.map.assert_called_once()

    @patch("asta.pdf.batch_extract.Pool")
    @patch("asta.pdf.batch_extract.cpu_count")
    def test_batch_extract_with_failures(
        self, mock_cpu_count, mock_pool, runner, tmp_path
    ):
        """Test batch extraction with some failures."""
        # Create fake PDF files
        pdf1 = tmp_path / "test1.pdf"
        pdf2 = tmp_path / "test2.pdf"
        pdf1.write_bytes(b"%PDF-1.4 fake")
        pdf2.write_bytes(b"%PDF-1.4 fake")

        output_dir = tmp_path / "output"

        # Mock CPU count
        mock_cpu_count.return_value = 4

        # Mock the pool - one success, one failure
        mock_pool_instance = MagicMock()
        mock_pool.return_value.__enter__.return_value = mock_pool_instance
        mock_pool_instance.map.return_value = [
            {
                "success": True,
                "input": str(pdf1),
                "output": str(output_dir / "test1.md"),
            },
            {"success": False, "input": str(pdf2), "error": "Invalid PDF"},
        ]

        # Run command
        result = runner.invoke(
            cli, ["pdf", "batch-extract", str(pdf1), str(pdf2), "-o", str(output_dir)]
        )

        # Verify
        assert result.exit_code == 1  # Should exit with error
        assert "Successfully processed 1 PDFs" in result.output
        assert "Failed to process 1 PDFs" in result.output
        assert "Invalid PDF" in result.output

    @patch("asta.pdf.batch_extract.Pool")
    @patch("asta.pdf.batch_extract.cpu_count")
    def test_batch_extract_custom_workers(
        self, mock_cpu_count, mock_pool, runner, tmp_path
    ):
        """Test batch extraction with custom worker count."""
        pdf1 = tmp_path / "test1.pdf"
        pdf1.write_bytes(b"%PDF-1.4 fake")

        output_dir = tmp_path / "output"

        mock_cpu_count.return_value = 8

        # Mock the pool
        mock_pool_instance = MagicMock()
        mock_pool.return_value.__enter__.return_value = mock_pool_instance
        mock_pool_instance.map.return_value = [
            {
                "success": True,
                "input": str(pdf1),
                "output": str(output_dir / "test1.md"),
            }
        ]

        # Run with custom workers
        result = runner.invoke(
            cli,
            [
                "pdf",
                "batch-extract",
                str(pdf1),
                "-o",
                str(output_dir),
                "--workers",
                "2",
            ],
        )

        # Verify
        assert result.exit_code == 0
        assert (
            "Processing 1 PDFs with 1 workers" in result.output
        )  # Min of workers and file count

    @patch("asta.pdf.batch_extract.Pool")
    @patch("asta.pdf.batch_extract.cpu_count")
    def test_batch_extract_json_format(
        self, mock_cpu_count, mock_pool, runner, tmp_path
    ):
        """Test batch extraction with JSON format."""
        pdf1 = tmp_path / "test1.pdf"
        pdf1.write_bytes(b"%PDF-1.4 fake")

        output_dir = tmp_path / "output"

        mock_cpu_count.return_value = 4

        # Mock the pool
        mock_pool_instance = MagicMock()
        mock_pool.return_value.__enter__.return_value = mock_pool_instance
        mock_pool_instance.map.return_value = [
            {
                "success": True,
                "input": str(pdf1),
                "output": str(output_dir / "test1.json"),
            }
        ]

        # Run with JSON format
        result = runner.invoke(
            cli,
            [
                "pdf",
                "batch-extract",
                str(pdf1),
                "-o",
                str(output_dir),
                "--format",
                "json",
            ],
        )

        # Verify
        assert result.exit_code == 0
