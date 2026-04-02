#!/usr/bin/env python3
"""Version management script for asta-plugins.

Handles setting versions and checking version consistency across all files.
"""

import json
import re
import sys
from pathlib import Path

# Colors for terminal output
RED = "\033[0;31m"
GREEN = "\033[0;32m"
YELLOW = "\033[1;33m"
NC = "\033[0m"  # No Color

# Project paths
SCRIPT_DIR = Path(__file__).parent
PROJECT_ROOT = SCRIPT_DIR.parent

INIT_FILE = PROJECT_ROOT / "src" / "asta" / "__init__.py"
PYPROJECT_FILE = PROJECT_ROOT / "pyproject.toml"
MARKETPLACE_FILE = PROJECT_ROOT / ".claude-plugin" / "marketplace.json"
SKILLS_DIR = PROJECT_ROOT / "skills"
HOOK_FILE = PROJECT_ROOT / "hooks" / "sync-cli-version.sh"


def get_init_version() -> str:
    """Read version from src/asta/__init__.py."""
    content = INIT_FILE.read_text()
    match = re.search(r'__version__ = "([^"]+)"', content)
    if not match:
        raise ValueError("Could not find __version__ in __init__.py")
    return match.group(1)


def get_pyproject_version() -> str:
    """Read version from pyproject.toml."""
    content = PYPROJECT_FILE.read_text()
    match = re.search(r'^version = "([^"]+)"', content, re.MULTILINE)
    if not match:
        raise ValueError("Could not find version in pyproject.toml")
    return match.group(1)


def get_marketplace_versions() -> dict[str, str]:
    """Read versions for all plugins from .claude-plugin/marketplace.json."""
    data = json.loads(MARKETPLACE_FILE.read_text())
    return {p["name"]: p["version"] for p in data["plugins"]}


def get_skills_versions() -> list[str]:
    """Read all PLUGIN_VERSION values from skills/*/SKILL.md files."""
    versions = set()
    for skill_file in SKILLS_DIR.glob("*/SKILL.md"):
        content = skill_file.read_text()
        matches = re.findall(r"PLUGIN_VERSION=([0-9.]+)", content)
        versions.update(matches)
    return sorted(versions)


def get_hook_version() -> str:
    """Read PLUGIN_VERSION from hooks/sync-cli-version.sh."""
    content = HOOK_FILE.read_text()
    match = re.search(r"PLUGIN_VERSION=([0-9.]+)", content)
    if not match:
        raise ValueError("Could not find PLUGIN_VERSION in sync-cli-version.sh")
    return match.group(1)


def check_version_consistency() -> bool:
    """Check if all version locations have the same version.

    Returns:
        True if all versions match, False otherwise.
    """
    init_version = get_init_version()
    pyproject_version = get_pyproject_version()
    marketplace_versions = get_marketplace_versions()
    skills_versions = get_skills_versions()
    hook_version = get_hook_version()

    mismatch = False

    # Check core files
    if init_version != pyproject_version:
        mismatch = True

    # Check all marketplace plugins
    for name, version in marketplace_versions.items():
        if version != init_version:
            mismatch = True

    # Check skills files
    if len(skills_versions) != 1 or skills_versions[0] != init_version:
        mismatch = True

    # Check hook file
    if hook_version != init_version:
        mismatch = True

    if mismatch:
        print(f"{RED}Error: Version mismatch detected:{NC}")
        print(f"  src/asta/__init__.py:            {init_version}")
        print(f"  pyproject.toml:                  {pyproject_version}")
        for name, version in marketplace_versions.items():
            label = f"  marketplace.json ({name}):"
            print(f"{label:<39}{version}")
        print(f"  skills/*/SKILL.md:               {', '.join(skills_versions)}")
        print(f"  hooks/sync-cli-version.sh:       {hook_version}")
        print()
        print("Run 'make set-version VERSION=x.y.z' to sync versions")
        return False

    print(f"{GREEN}✓ All version files are consistent: {init_version}{NC}")
    return True


def validate_version_format(version: str) -> bool:
    """Validate that version is in semver format (x.y.z).

    Args:
        version: Version string to validate.

    Returns:
        True if valid, False otherwise.
    """
    return bool(re.match(r"^\d+\.\d+\.\d+$", version))


def set_version(new_version: str) -> bool:
    """Set version in all files.

    Args:
        new_version: New version string in x.y.z format.

    Returns:
        True if successful, False otherwise.
    """
    if not validate_version_format(new_version):
        print(f"{RED}Error: Version must be in format x.y.z (e.g., 1.2.3){NC}")
        return False

    print(f"Setting version to {new_version} in all files...")

    # Update src/asta/__init__.py
    print("Updating src/asta/__init__.py...")
    content = INIT_FILE.read_text()
    content = re.sub(
        r'__version__ = "[^"]+"', f'__version__ = "{new_version}"', content
    )
    INIT_FILE.write_text(content)

    # Update pyproject.toml
    print("Updating pyproject.toml...")
    content = PYPROJECT_FILE.read_text()
    content = re.sub(
        r'^version = "[^"]+"', f'version = "{new_version}"', content, flags=re.MULTILINE
    )
    PYPROJECT_FILE.write_text(content)

    # Update .claude-plugin/marketplace.json
    print("Updating .claude-plugin/marketplace.json...")
    data = json.loads(MARKETPLACE_FILE.read_text())
    for plugin in data["plugins"]:
        plugin["version"] = new_version
    MARKETPLACE_FILE.write_text(json.dumps(data, indent=2) + "\n")

    # Update skill installation sections
    print("Updating skill installation sections...")
    for skill_file in SKILLS_DIR.glob("*/SKILL.md"):
        content = skill_file.read_text()
        content = re.sub(
            r"PLUGIN_VERSION=\d+\.\d+\.\d+", f"PLUGIN_VERSION={new_version}", content
        )
        skill_file.write_text(content)

    # Update sync-version hook
    print("Updating sync-version hook...")
    content = HOOK_FILE.read_text()
    content = re.sub(
        r"PLUGIN_VERSION=\d+\.\d+\.\d+", f"PLUGIN_VERSION={new_version}", content
    )
    HOOK_FILE.write_text(content)

    print(f"{GREEN}✓ Version updated to {new_version} in all files{NC}")
    print()
    print(f"{YELLOW}Next steps:{NC}")
    print("  1. Review changes: git diff")
    print("  2. Rebuild plugins: make build-plugins")
    print(
        f"  3. Commit changes: git add -A && git commit -m 'chore: bump version to {new_version}'"
    )

    return True


def show_version() -> None:
    """Show current version from __init__.py."""
    print(get_init_version())


def main() -> int:
    """Main entry point."""
    if len(sys.argv) < 2:
        print("Usage: manage-version.py {check|set VERSION|show}")
        print()
        print("Commands:")
        print("  check      Check version consistency across all files")
        print("  set        Set version in all files (requires VERSION argument)")
        print("  show       Show current version from __init__.py")
        return 1

    command = sys.argv[1]

    if command == "check":
        return 0 if check_version_consistency() else 1
    elif command == "set":
        if len(sys.argv) < 3:
            print(f"{RED}Error: VERSION parameter is required{NC}")
            print("Usage: manage-version.py set VERSION")
            return 1
        return 0 if set_version(sys.argv[2]) else 1
    elif command == "show":
        show_version()
        return 0
    else:
        print(f"{RED}Error: Unknown command '{command}'{NC}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
