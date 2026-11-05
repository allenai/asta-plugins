# Build from this checkout's workspace assets, so a release's demo uses that release.
ASTA_WORKSPACE_ASSETS := ../../plugins/asta-tools/skills/workspace/assets
ASTA_WORKSPACE_SCRIPTS := $(ASTA_WORKSPACE_ASSETS)
include $(ASTA_WORKSPACE_ASSETS)/workspace.mk
