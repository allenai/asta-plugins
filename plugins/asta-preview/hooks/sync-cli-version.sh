#!/bin/bash
# Check if asta CLI version matches the plugin version and auto-install/update if needed

PLUGIN_VERSION=0.9.0
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

# Compare versions
if [ "$CLI_VERSION" != "$PLUGIN_VERSION" ]; then
    echo "🔄 Updating Asta CLI from $CLI_VERSION to $PLUGIN_VERSION..."
    if uv tool install --force "$INSTALL_URL"; then
        echo "✅ Asta CLI updated to $PLUGIN_VERSION successfully"
    else
        echo "❌ Failed to update Asta CLI"
        exit 1
    fi
fi
