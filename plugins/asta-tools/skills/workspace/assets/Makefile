# Keep project targets here; the shared targets come from the selected
# asta-plugins version. Commit workspace.mk to take ownership of them.
ifndef ASTA_PLUGINS_REF
ASTA_PLUGINS_REF := $(shell awk '/^[[:space:]]*uses:[[:space:]]*/ && /allenai\/asta-plugins\/\.github\/workflows\/workspace-quarto-site\.yml@/ { sub(/^.*workspace-quarto-site\.yml@/, ""); sub(/[^A-Za-z0-9._\/-].*$$/, ""); print; exit }' .github/workflows/docs.yml 2>/dev/null)
endif
ifeq ($(strip $(ASTA_PLUGINS_REF)),)
ASTA_PLUGINS_REF := v0.104.1
endif
ASTA_PLUGINS_REPO ?= https://github.com/allenai/asta-plugins
ASTA_PLUGINS_ARCHIVE_URL ?=

ifneq ($(shell git ls-files --error-unmatch workspace.mk 2>/dev/null),)
include workspace.mk
else
ASTA_WORKSPACE_MK := .asta/cache/$(ASTA_PLUGINS_REF)/workspace.mk
include $(ASTA_WORKSPACE_MK)

# Floating channels refresh at most once an hour. A failed refresh keeps the
# last working copy so local work can continue offline.
ifneq ($(filter main latest,$(ASTA_PLUGINS_REF)),)
ifeq ($(shell find $(ASTA_WORKSPACE_MK) -mmin -60 -type f -print 2>/dev/null),)
.PHONY: workspace-ref-check
$(ASTA_WORKSPACE_MK): workspace-ref-check
endif
endif

$(ASTA_WORKSPACE_MK):
	@set -eu; \
	ref='$(ASTA_PLUGINS_REF)'; \
	case "$$ref" in *[!A-Za-z0-9._/-]*|*..*|/*) echo "invalid asta-plugins ref: $$ref" >&2; exit 1;; esac; \
	url='$(ASTA_PLUGINS_ARCHIVE_URL)'; \
	if [ -z "$$url" ]; then \
		case "$$ref" in \
			latest|main) url='$(ASTA_PLUGINS_REPO)/archive/refs/heads/'"$$ref"'.tar.gz';; \
			v[0-9]*.[0-9]*.[0-9]*) url='$(ASTA_PLUGINS_REPO)/archive/refs/tags/'"$$ref"'.tar.gz';; \
			*) url='$(ASTA_PLUGINS_REPO)/archive/'"$$ref"'.tar.gz';; \
		esac; \
	fi; \
	tmp=$$(mktemp -d); trap 'rm -rf "$$tmp"' EXIT HUP INT TERM; \
	if ! curl -fsSL --connect-timeout 5 --max-time 30 "$$url" -o "$$tmp/archive.tar.gz"; then \
		if [ -s "$@" ]; then touch "$@"; echo "workspace: using cached Makefile; refresh failed" >&2; exit 0; fi; \
		echo "workspace: cannot fetch managed Makefile from $$url" >&2; exit 1; \
	fi; \
	entry=$$(tar -tzf "$$tmp/archive.tar.gz" | grep '/plugins/asta-tools/skills/workspace/assets/workspace.mk$$' | head -n 1); \
	if [ -z "$$entry" ]; then entry=$$(tar -tzf "$$tmp/archive.tar.gz" | grep '/plugins/asta-tools/skills/workspace/assets/Makefile$$' | head -n 1); fi; \
	[ -n "$$entry" ] || { echo "workspace: no managed Makefile in $$url" >&2; exit 1; }; \
	tar -xzOf "$$tmp/archive.tar.gz" "$$entry" > "$$tmp/workspace.mk"; \
	[ -s "$$tmp/workspace.mk" ] || { echo "workspace: empty managed Makefile in $$url" >&2; exit 1; }; \
	mkdir -p "$$(dirname "$@")"; \
	mv "$$tmp/workspace.mk" "$@"
endif
