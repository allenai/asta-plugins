#!/bin/bash
# Check if asta CLI version matches the plugin version and auto-install/update if needed

PLUGIN_VERSION=0.128.0
REPO_URL="https://github.com/allenai/asta-plugins.git"
INSTALL_URL="git+$REPO_URL@v$PLUGIN_VERSION"

# A merged version bump is tagged only after its release checks pass, so a
# plugin updated from main can name a version with no tag yet. Exit 2 means
# git reached the remote and the tag is absent.
tag_missing() {
    GIT_TERMINAL_PROMPT=0 git ls-remote --exit-code --tags "$REPO_URL" "refs/tags/v$PLUGIN_VERSION" >/dev/null 2>&1
    [ $? -eq 2 ]
}

# Check if asta is installed
if ! command -v asta &> /dev/null; then
    if tag_missing; then
        echo "📦 Asta CLI $PLUGIN_VERSION isn't released yet; installing the latest release..."
        if uv tool install "git+$REPO_URL@latest"; then
            echo "✅ Latest Asta CLI release installed"
        else
            echo "❌ Failed to install Asta CLI"
            exit 1
        fi
        exit 0
    fi
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
    if tag_missing; then
        echo "ℹ️ Asta CLI $PLUGIN_VERSION isn't released yet; keeping $CLI_VERSION until it is"
        exit 0
    fi
    echo "🔄 Updating Asta CLI from $CLI_VERSION to $PLUGIN_VERSION..."
    if uv tool install --force "$INSTALL_URL"; then
        echo "✅ Asta CLI updated to $PLUGIN_VERSION successfully"
    else
        echo "❌ Failed to update Asta CLI"
        exit 1
    fi
fi
