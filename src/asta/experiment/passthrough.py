"""Pass-through command for panda experiment runner"""

from asta.utils.passthrough import create_passthrough_command

# Fixed version tag for panda installation
# Update this when you want to pin to a specific release
# For pip installation (future): install via PyPI instead of git
PANDA_VERSION = "main"  # Update to a specific tag when available

# Create the experiment passthrough command
experiment = create_passthrough_command(
    tool_name="panda",
    install_source="git+https://github.com/allenai/panda",
    version=PANDA_VERSION,
    command_name="experiment",
    friendly_name="panda",
    docstring="""Run computational experiments (pass-through to panda CLI).

This command passes all arguments directly to the panda experiment runner.
If panda is not installed, it will be installed automatically.

Examples:
    asta experiment --task "Assess GPT-4 translation quality" --force_report
    asta experiment --task_file task.txt --outputs_dir ./experiments/
    asta experiment --help

For full documentation, run: asta experiment --help
""",
)
