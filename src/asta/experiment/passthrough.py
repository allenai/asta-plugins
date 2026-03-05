"""Pass-through command for panda experiment runner"""

from asta.utils.config import get_passthrough_config
from asta.utils.passthrough import create_passthrough_command

# Load configuration from passthrough.conf
config = get_passthrough_config("experiment")

# Create the experiment passthrough command
experiment = create_passthrough_command(
    tool_name=config["tool_name"],
    install_type=config["install_type"],
    install_source=config["install_source"],
    minimum_version=config["minimum_version"],
    command_name=config["command_name"],
    friendly_name=config["friendly_name"],
    docstring=config["docstring"],
)
