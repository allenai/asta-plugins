# Keep project targets here; the shared targets come from the selected
# asta-plugins version. Commit workspace.mk to take ownership of them.
# Cleaning a project must also work before the first managed-file fetch.
ASTA_LOCAL_MK := $(shell git ls-files --error-unmatch workspace.mk 2>/dev/null)
ifneq ($(MAKECMDGOALS),)
ifeq ($(filter-out clean,$(MAKECMDGOALS)),)
ifneq ($(ASTA_LOCAL_MK),)
ifeq ($(wildcard workspace.mk),)
$(error workspace.mk is tracked but missing; restore it or remove it from Git)
endif
include workspace.mk
else
# Offline cleanup intentionally removes only local Quarto build output.
.PHONY: clean
clean:
	rm -rf _site .quarto
endif
else
ASTA_LOAD_WORKSPACE_MK := 1
endif
else
ASTA_LOAD_WORKSPACE_MK := 1
endif

ifeq ($(ASTA_LOAD_WORKSPACE_MK),1)
ifneq ($(origin ASTA_PLUGINS_REF),undefined)
override ASTA_PLUGINS_REF := $(value ASTA_PLUGINS_REF)
endif
ASTA_PLUGINS_REPO ?= https://github.com/allenai/asta-plugins
ASTA_PLUGINS_ARCHIVE_URL ?=
ifndef ASTA_PLUGINS_REF
ASTA_PLUGINS_REF := $(shell awk '/^[[:space:]]*uses:[[:space:]]*/ && /allenai\/asta-plugins\/\.github\/workflows\/workspace-quarto-site\.yml@/ { sub(/^.*workspace-quarto-site\.yml@/, ""); sub(/[^A-Za-z0-9._\/-].*$$/, ""); print; exit }' .github/workflows/docs.yml 2>/dev/null)
endif
ifeq ($(strip $(ASTA_PLUGINS_REF)),)
ASTA_PLUGINS_REF := $(shell git ls-remote --tags --refs "$(ASTA_PLUGINS_REPO)" 'v*' 2>/dev/null | awk -F/ '{print $$NF}' | grep -E '^v[0-9]+\.[0-9]+\.[0-9]+$$' | sort -V | tail -n 1)
endif

ifneq ($(ASTA_LOCAL_MK),)
ifeq ($(wildcard workspace.mk),)
$(error workspace.mk is tracked but missing; restore it or remove it from Git)
endif
include workspace.mk
else
ifneq ($(wildcard workspace.mk),)
$(warning workspace.mk is untracked; commit it to use it as a local override)
endif
ifeq ($(strip $(ASTA_PLUGINS_REF)),)
$(error Cannot find an asta-plugins release ref; set ASTA_PLUGINS_REF explicitly)
endif
ifneq ($(findstring ..,$(ASTA_PLUGINS_REF)),)
$(error Invalid asta-plugins ref: $(ASTA_PLUGINS_REF))
endif
ifneq ($(filter /%,$(ASTA_PLUGINS_REF)),)
$(error Invalid asta-plugins ref: $(ASTA_PLUGINS_REF))
endif
define ASTA_NEWLINE


endef
ifneq ($(findstring $(ASTA_NEWLINE),$(ASTA_PLUGINS_REF)),)
$(error Invalid asta-plugins ref: line breaks are not allowed)
endif
ifneq ($(shell printf '%s\n' '$(subst ','"'"',$(ASTA_PLUGINS_REF))' | LC_ALL=C awk 'NR != 1 || $$0 !~ /^[A-Za-z0-9_./-]+$$/ { invalid = 1 } END { if (NR == 1 && !invalid) print "valid" }'),valid)
$(error Invalid asta-plugins ref: $(ASTA_PLUGINS_REF))
endif
ASTA_WORKSPACE_MK := .asta/cache/$(ASTA_PLUGINS_REF)/workspace.mk
include $(ASTA_WORKSPACE_MK)

# Floating channels refresh at most once an hour. A failed refresh keeps the
# last working copy so local work can continue offline.
ifneq ($(filter main latest,$(ASTA_PLUGINS_REF)),)
ifeq ($(shell find $(ASTA_WORKSPACE_MK) -mmin -60 -type f -print 2>/dev/null),)
.PHONY: workspace-ref-check
workspace-ref-check: ;
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
	tmp=$$(mktemp -d); trap 'rm -rf "$$tmp"' EXIT; trap 'exit 1' HUP INT TERM; \
	if ! curl -fsSL --connect-timeout 5 --max-time 120 "$$url" -o "$$tmp/archive.tar.gz"; then \
		if [ -s "$@" ]; then touch "$@"; echo "workspace: using cached Makefile; refresh failed" >&2; exit 0; fi; \
		echo "workspace: cannot fetch managed Makefile from $$url" >&2; exit 1; \
	fi; \
	entry=$$(tar -tzf "$$tmp/archive.tar.gz" | grep '/plugins/asta-tools/skills/workspace/assets/workspace\.mk$$' | head -n 1); \
	legacy=0; \
	if [ -z "$$entry" ]; then legacy=1; entry=$$(tar -tzf "$$tmp/archive.tar.gz" | grep '/plugins/asta-tools/skills/workspace/assets/Makefile$$' | head -n 1); fi; \
	[ -n "$$entry" ] || { echo "workspace: no managed Makefile in $$url" >&2; exit 1; }; \
	tar -xzOf "$$tmp/archive.tar.gz" "$$entry" > "$$tmp/workspace.mk"; \
	[ -s "$$tmp/workspace.mk" ] || { echo "workspace: empty managed Makefile in $$url" >&2; exit 1; }; \
	if [ "$$legacy" -eq 1 ] && grep -q 'ASTA_WORKSPACE_MK' "$$tmp/workspace.mk"; then \
		echo "workspace: $$ref does not provide a managed workspace.mk" >&2; exit 1; \
	fi; \
	mkdir -p "$$(dirname "$@")"; \
	mv "$$tmp/workspace.mk" "$@"
endif
endif
