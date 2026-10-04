# Keep project targets here; the shared targets come from the selected
# asta-plugins version. Commit workspace.mk to take ownership of them.
# Cleaning a project must also work before the first managed-file fetch.
.DEFAULT_GOAL := dev
ASTA_LOCAL_MK := $(shell git ls-files --error-unmatch workspace.mk 2>/dev/null)
ifneq ($(ASTA_LOCAL_MK),)
ifeq ($(wildcard workspace.mk),)
$(error workspace.mk is tracked but missing; restore it or remove it from Git)
endif
include workspace.mk
else
ifneq ($(MAKECMDGOALS),)
ifeq ($(filter-out clean,$(MAKECMDGOALS)),)
# Offline cleanup intentionally removes only local Quarto build output.
.PHONY: clean
clean:
	rm -rf _site .quarto
else
ASTA_LOAD_WORKSPACE_MK := 1
endif
else
ASTA_LOAD_WORKSPACE_MK := 1
endif

ifeq ($(ASTA_LOAD_WORKSPACE_MK),1)
ASTA_REF_ORIGIN := $(origin ASTA_PLUGINS_REF)
ifneq ($(origin ASTA_PLUGINS_REF),undefined)
override ASTA_PLUGINS_REF := $(value ASTA_PLUGINS_REF)
endif
ifeq ($(ASTA_REF_ORIGIN),environment)
$(warning ASTA_PLUGINS_REF from the environment overrides docs.yml; local builds may differ from CI)
endif
ASTA_PLUGINS_REPO ?= https://github.com/allenai/asta-plugins
ASTA_PLUGINS_ARCHIVE_URL ?=
ifndef ASTA_PLUGINS_REF
ASTA_PLUGINS_REF := $(shell awk '/^[[:space:]]*uses:[[:space:]]*/ && /allenai\/asta-plugins\/\.github\/workflows\/workspace-quarto-site\.yml@/ { sub(/^.*workspace-quarto-site\.yml@/, ""); sub(/[^A-Za-z0-9._\/-].*$$/, ""); print; exit }' .github/workflows/docs.yml 2>/dev/null)
endif
ifeq ($(strip $(ASTA_PLUGINS_REF)),)
ifneq ($(wildcard .github/workflows/docs.yml),)
$(error Cannot read the asta-plugins workflow ref from docs.yml; fix it or set ASTA_PLUGINS_REF explicitly)
endif
ASTA_DEFAULT_RELEASE := 1
ASTA_PLUGINS_REF := $(shell git ls-remote --tags --refs "$(ASTA_PLUGINS_REPO)" 'v*' 2>/dev/null | awk -F/ '{print $$NF}' | grep -E '^v[0-9]+\.[0-9]+\.[0-9]+$$' | sort -V | tail -n 1)
ifeq ($(strip $(ASTA_PLUGINS_REF)),)
ASTA_PLUGINS_REF := $(shell ref=$$(cat .asta/cache/default-release 2>/dev/null); if [ -s ".asta/cache/$$ref/workspace.mk" ]; then printf '%s' "$$ref"; fi)
ifeq ($(strip $(ASTA_PLUGINS_REF)),)
ASTA_PLUGINS_REF := $(shell find .asta/cache -mindepth 2 -maxdepth 2 -type f -name workspace.mk -size +0c 2>/dev/null | awk -F/ '$$3 ~ /^v[0-9]+\.[0-9]+\.[0-9]+$$/ { print $$3 }' | sort -V | tail -n 1)
endif
ifneq ($(strip $(ASTA_PLUGINS_REF)),)
$(warning Cannot look up asta-plugins releases; using cached $(ASTA_PLUGINS_REF))
endif
endif
endif

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

.PHONY: workspace-check-gate
check: workspace-check-gate
workspace-check-gate:
	@test "$(ASTA_WORKSPACE_CHECK)" = 1 || { echo "selected workspace.mk does not provide the shared check gate" >&2; exit 1; }

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
	case "$$ref" in *[!A-Za-z0-9_./-]*|*..*|/*) echo "invalid asta-plugins ref: $$ref" >&2; exit 1;; esac; \
	url='$(subst ','"'"',$(ASTA_PLUGINS_ARCHIVE_URL))'; \
	if [ -z "$$url" ]; then \
		case "$$ref" in \
			latest|main) url='$(subst ','"'"',$(ASTA_PLUGINS_REPO))/archive/refs/heads/'"$$ref"'.tar.gz';; \
			v[0-9]*.[0-9]*.[0-9]*) url='$(subst ','"'"',$(ASTA_PLUGINS_REPO))/archive/refs/tags/'"$$ref"'.tar.gz';; \
			*) url='$(subst ','"'"',$(ASTA_PLUGINS_REPO))/archive/'"$$ref"'.tar.gz';; \
		esac; \
	fi; \
	tmp=$$(mktemp -d); trap 'rm -rf "$$tmp"' EXIT; trap 'exit 1' HUP INT TERM; \
	failure="workspace: cannot fetch managed Makefile from $$url"; \
	if curl -fsSL --connect-timeout 5 --max-time 120 "$$url" -o "$$tmp/archive.tar.gz"; then \
		failure="workspace: invalid managed Makefile archive from $$url"; \
		if tar -tzf "$$tmp/archive.tar.gz" >/dev/null 2>&1; then \
			entry=$$(tar -tzf "$$tmp/archive.tar.gz" | grep '/plugins/asta-tools/skills/workspace/assets/workspace\.mk$$' | head -n 1) || :; \
			if [ -z "$$entry" ]; then \
				failure="workspace: $$ref does not provide a managed workspace.mk; choose a newer ref or commit a custom workspace.mk"; \
			elif tar -xzOf "$$tmp/archive.tar.gz" "$$entry" > "$$tmp/workspace.mk" && [ -s "$$tmp/workspace.mk" ]; then \
				mkdir -p "$$(dirname "$@")"; mv "$$tmp/workspace.mk" "$@"; \
				if [ "$(ASTA_DEFAULT_RELEASE)" = 1 ]; then \
					ref_file=$$(mktemp .asta/cache/.default-release.XXXXXX); \
					printf '%s\n' "$$ref" > "$$ref_file"; mv "$$ref_file" .asta/cache/default-release; \
				fi; \
				exit 0; \
			fi; \
		fi; \
	fi; \
	if [ -s "$@" ]; then touch "$@"; echo "workspace: using cached Makefile; refresh failed ($$failure)" >&2; exit 0; fi; \
	echo "$$failure" >&2; exit 1
endif
endif
