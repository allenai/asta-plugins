"""Passthrough command for olmOCR CLI."""

from asta.utils.auth_helper import get_access_token
from asta.utils.config import get_api_config, get_config, get_passthrough_config
from asta.utils.passthrough import create_passthrough_command

# Load configuration from asta.conf
config = get_passthrough_config("pdf-extraction")


def get_pdf_extraction_tool_args() -> list[str]:
    """Get PDF extraction tool arguments with authentication token (lazy evaluation)."""
    # Get olmOCR API configuration
    api_config = get_api_config("olmocr")
    server_url = api_config["base_url"]

    # Get authentication token (only when command is invoked)
    auth_token = get_access_token()

    # Get model name
    model = get_config()["apis"]["olmocr"]["model"]

    return [
        "--server",
        server_url,
        "--api_key",
        auth_token,
        "--model",
        model,
        "--workers",
        "1",  # Don't overload the backend
    ]


_HELP_TEXT = """\
usage: asta pdf-extraction [-h] [--pdfs [PDFS ...]] [--model MODEL]
              [--workspace_profile WORKSPACE_PROFILE]
              [--pdf_profile PDF_PROFILE] [--pages_per_group PAGES_PER_GROUP]
              [--max_page_retries MAX_PAGE_RETRIES]
              [--max_page_error_rate MAX_PAGE_ERROR_RATE]
              [--max_concurrent_requests MAX_CONCURRENT_REQUESTS]
              [--max_server_ready_timeout MAX_SERVER_READY_TIMEOUT]
              [--apply_filter] [--stats] [--markdown]
              [--target_longest_image_dim TARGET_LONGEST_IMAGE_DIM]
              [--target_anchor_text_len TARGET_ANCHOR_TEXT_LEN]
              [--guided_decoding] [--disk_logging [DISK_LOGGING]]
              [--gpu-memory-utilization GPU_MEMORY_UTILIZATION]
              [--max_model_len MAX_MODEL_LEN]
              [--tensor-parallel-size TENSOR_PARALLEL_SIZE]
              [--data-parallel-size DATA_PARALLEL_SIZE]
              workspace

Manager for running millions of PDFs through a batch inference pipeline.

positional arguments:
  workspace             The filesystem path where work will be stored, can be
                        a local folder, or an s3 path if coordinating work
                        with many workers, s3://bucket/prefix/

options:
  -h, --help            show this help message and exit
  --pdfs [PDFS ...]     Path to add pdfs stored in s3 to the workspace, can be
                        a glob path s3://bucket/prefix/*.pdf or path to file
                        containing list of pdf paths
  --model MODEL         Path where the model is located,
                        allenai/olmOCR-2-7B-1025-FP8 is the default, can be
                        local, s3, or hugging face.
  --workspace_profile WORKSPACE_PROFILE
                        S3 configuration profile for accessing the workspace
  --pdf_profile PDF_PROFILE
                        S3 configuration profile for accessing the raw pdf
                        documents
  --pages_per_group PAGES_PER_GROUP
                        Aiming for this many pdf pages per work item group
  --max_page_retries MAX_PAGE_RETRIES
                        Max number of times we will retry rendering a page
  --max_page_error_rate MAX_PAGE_ERROR_RATE
                        Rate of allowable failed pages in a document, 1/250 by
                        default
  --max_concurrent_requests MAX_CONCURRENT_REQUESTS
                        Max number of concurrent VLLM server requests at a
                        time.
  --max_server_ready_timeout MAX_SERVER_READY_TIMEOUT
                        Number of seconds to wait for vllm to become ready
                        before exiting.
  --apply_filter        Apply basic filtering to English pdfs which are not
                        forms, and not likely seo spam
  --stats               Instead of running any job, reports some statistics
                        about the current workspace
  --markdown            Also write natural text to markdown files preserving
                        the folder structure of the input pdfs
  --target_longest_image_dim TARGET_LONGEST_IMAGE_DIM
                        Dimension on longest side to use for rendering the pdf
                        pages
  --target_anchor_text_len TARGET_ANCHOR_TEXT_LEN
                        Maximum amount of anchor text to use (characters), not
                        used for new models
  --guided_decoding     Enable guided decoding for model YAML type outputs
  --disk_logging [DISK_LOGGING]
                        Enable writing logs to disk, optionally specify
                        filename (default: olmocr-pipeline-debug.log)

VLLM arguments:
  These arguments are passed to vLLM. Any unrecognized arguments are also
  automatically forwarded to vLLM.

  --gpu-memory-utilization GPU_MEMORY_UTILIZATION
                        Fraction of VRAM vLLM may pre-allocate for KV-cache
                        (passed through to vllm serve).
  --max_model_len MAX_MODEL_LEN
                        Upper bound (tokens) vLLM will allocate KV-cache for,
                        lower if VLLM won't start
  --tensor-parallel-size TENSOR_PARALLEL_SIZE, -tp TENSOR_PARALLEL_SIZE
                        Tensor parallel size for vLLM
  --data-parallel-size DATA_PARALLEL_SIZE, -dp DATA_PARALLEL_SIZE
                        Data parallel size for vLLM
"""

# Create the passthrough command with tool arguments
pdf_extraction = create_passthrough_command(
    tool_name=config["tool_name"],
    install_type=config["install_type"],
    install_source=config["install_source"],
    minimum_version=config["minimum_version"],
    command_name=config["command_name"],
    docstring=config["docstring"],
    tool_args=get_pdf_extraction_tool_args,  # Pass callable, not the result
    help_transform=lambda _: _HELP_TEXT,
)
