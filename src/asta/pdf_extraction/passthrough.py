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
    ]


# Create the passthrough command with tool arguments
pdf_extraction = create_passthrough_command(
    tool_name=config["tool_name"],
    install_type=config["install_type"],
    install_source=config["install_source"],
    minimum_version=config["minimum_version"],
    command_name=config["command_name"],
    docstring=config["docstring"],
    tool_args=get_pdf_extraction_tool_args,  # Pass callable, not the result
)
