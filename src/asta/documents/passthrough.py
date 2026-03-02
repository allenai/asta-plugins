"""Pass-through command for asta-documents CLI"""

from asta.utils.passthrough import create_passthrough_command

# Fixed version tag for asta-documents installation
# Update this when you want to pin to a specific release
# For pip installation (future): install via PyPI instead of git
ASTA_DOCUMENTS_VERSION = "v0.1.0"

# Create the documents passthrough command
documents = create_passthrough_command(
    tool_name="asta-documents",
    install_source="git+ssh://git@github.com/allenai/asta-resource-repo.git",
    version=ASTA_DOCUMENTS_VERSION,
    command_name="documents",
    friendly_name="asta-documents",
    docstring="""Document metadata index management (pass-through to asta-documents CLI).

This command passes all arguments directly to the asta-documents CLI.
If asta-documents is not installed, it will be installed automatically.

Examples:
    asta documents list
    asta documents add <url> --name="Title" --summary="Description"
    asta documents search --summary="query"
    asta documents get <uuid>

For full documentation, run: asta documents --help
""",
)
