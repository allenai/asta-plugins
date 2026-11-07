#!/bin/bash
# Install missing/older Asta CLIs; keep newer versions shared by other projects.

PLUGIN_VERSION=0.125.0
INSTALL_URL="git+https://github.com/allenai/asta-plugins.git@v$PLUGIN_VERSION"

# Check if asta is installed
if ! command -v asta &> /dev/null; then
    echo "📦 Installing Asta CLI version $PLUGIN_VERSION..."
    if uv tool install "$INSTALL_URL"; then
        echo "✅ Asta CLI $PLUGIN_VERSION installed successfully"
    else
        echo "❌ Failed to install Asta CLI"
        exit 1
    fi
    exit 0
fi

# Get installed CLI version
CLI_VERSION=$(asta --version 2>/dev/null | grep -oE '[0-9]+\.[0-9]+\.[0-9]+')

# Do not replace a CLI whose version cannot be determined.
if [ -z "$CLI_VERSION" ]; then
    echo "⚠️ Could not determine Asta CLI version; leaving the installed CLI unchanged" >&2
    exit 0
fi

# Compare numeric components (portable to macOS; no sort -V dependency).
if awk -v installed="$CLI_VERSION" -v required="$PLUGIN_VERSION" 'BEGIN {
    split(installed, current, "."); split(required, minimum, ".")
    for (i = 1; i <= 3; i++) {
        if (current[i] + 0 < minimum[i] + 0) exit 0
        if (current[i] + 0 > minimum[i] + 0) exit 1
    }
    exit 1
}'; then
    echo "🔄 Updating Asta CLI from $CLI_VERSION to $PLUGIN_VERSION..."
    if uv tool install --force "$INSTALL_URL"; then
        echo "✅ Asta CLI updated to $PLUGIN_VERSION successfully"
    else
        echo "❌ Failed to update Asta CLI"
        exit 1
    fi
fi
