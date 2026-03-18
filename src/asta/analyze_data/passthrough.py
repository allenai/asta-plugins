"""Pass-through command for DataVoyager (dv) CLI"""

from asta.utils.config import get_config
from asta.utils.passthrough import create_passthrough_command

# Load configuration from asta.conf
config = get_config()["passthrough"]["analyze-data"]

# Create the analyze-data passthrough command
analyze_data = create_passthrough_command(
    tool_name=config["tool_name"],
    install_type=config["install_type"],
    install_source=config["install_source"],
    minimum_version=config["minimum_version"],
    command_name=config["command_name"],
    friendly_name=config["friendly_name"],
    docstring=config["docstring"],
)
