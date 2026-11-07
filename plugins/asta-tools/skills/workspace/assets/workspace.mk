# A committed scripts/<name> wins; otherwise use the copy `asta workspace sync` caches.
ASTA_WORKSPACE_MANAGED_SCRIPTS := 1
# Oldest asta CLI these rules work with; `asta workspace sync` checks it.
ASTA_WORKSPACE_MIN_CLI := 0.106.0
ASTA_WORKSPACE_SCRIPTS ?= .asta/cache/scripts
PYTHON ?= python3
ASTA_WORKSPACE_VIEWERS ?= 1
workspace_script = $(or $(firstword $(wildcard scripts/$(1) $(ASTA_WORKSPACE_SCRIPTS)/$(1))),$(error Missing $(1): update the Asta CLI and run 'asta workspace sync --refresh' or add scripts/$(1) to customize it))

.PHONY: preview render clean dev deployed-url check workspace-shared-check workspace-assets preview-baseline preview-ready workspace-viewers what-changed

# The project Makefile passes its selected workflow ref to the evidence fetch.
# Standalone use can set ASTA_PLUGINS_REF or resolve the latest release tag.
ASTA_PLUGINS_REPO ?= https://github.com/allenai/asta-plugins
ASTA_PLUGINS_REF ?=
# Derived from the repo + resolved ref unless set explicitly (tests point it at
# a local archive). When set, it is used verbatim and ref resolution is skipped.
ASTA_PLUGINS_ARCHIVE_URL ?=

# Managed Quarto extensions: the evidence filter and the Asta site theme. They
# are maintained with the workspace skill rather than vendored into every report.
# Replace them only after a complete download and extraction so a network failure
# cannot leave a partial extension behind.
#
# Offline-tolerant: if the network can't be reached (tag resolution or download
# fails) but all extensions referenced by _quarto.yml are cached, keep those
# copies and warn instead of failing. Missing required cached assets are a hard
# error. The theme ships its own fonts, so cached copies render offline.
# Keep .evidence-install.lock to serialize installs with older workspace rules.
workspace-assets:
	@set -eu; \
	theme_files="light.scss dark.scss asta.css asta-head.html fonts/Manrope.woff2 fonts/RobotoMono.woff2 fonts/Manrope-OFL.txt fonts/RobotoMono-OFL.txt"; \
	required_exts=evidence; \
	if find . -type d \( -path ./build -o -path ./_site -o -path ./venv -o -path ./paper-previews -o -name _extensions -o -name node_modules -o \( ! -path . -name '.*' \) -o \( ! -path . -exec test -e '{}/.git' \; \) \) -prune -o -type f \( -name slides.qmd -o \( -name '*.qmd' -exec grep -q 'asta-slides-revealjs' {} \; \) \) -print -quit | grep -q .; then \
		required_exts="$$required_exts asta-slides"; \
	fi; \
	if cat _quarto*.yml 2>/dev/null | sed '/^[[:space:]]*#/d' | grep -Eq '_extensions/asta-theme/(light\.scss|dark\.scss|asta\.css|asta-head\.html)'; then \
		required_exts="$$required_exts asta-theme"; \
	fi; \
	exts=; \
	for ext in $$required_exts; do \
		if [ -L "_extensions/$$ext" ]; then \
			echo "workspace-assets: _extensions/$$ext is a symlink (local development); not refreshing"; \
		elif git ls-files --error-unmatch "_extensions/$$ext" >/dev/null 2>&1; then \
			echo "workspace-assets: _extensions/$$ext is committed (customized copy); not refreshing"; \
		else exts="$$exts $$ext"; fi; \
	done; \
	[ -n "$$exts" ] || exit 0; \
	ref='$(subst ','"'"',$(value ASTA_PLUGINS_REF))'; \
	archive='$(subst ','"'"',$(value ASTA_WORKSPACE_ARCHIVE))'; \
	url='$(subst ','"'"',$(value ASTA_PLUGINS_ARCHIVE_URL))'; \
	repo='$(subst ','"'"',$(value ASTA_PLUGINS_REPO))'; \
	have_cache=1; \
	for ext in $$required_exts; do \
		[ -d "_extensions/$$ext" ] || have_cache=0; \
	done; \
	case " $$exts " in *' asta-theme '*) \
		for file in $$theme_files; do \
			[ -s "_extensions/asta-theme/$$file" ] || have_cache=0; \
		done ;; esac; \
	offline_ok() { \
		if [ "$$have_cache" -eq 1 ]; then \
			echo "workspace-assets: could not reach asta-plugins ($$1); keeping the cached extensions — re-run with network access to refresh" >&2; \
			exit 0; \
		fi; \
		echo "workspace-assets: could not reach asta-plugins ($$1) and no cached copy of all required extensions exists — network access is required for the first fetch" >&2; \
		exit 1; \
	}; \
	if [ -z "$$url" ]; then \
		if [ -z "$$ref" ]; then \
			ref=$$(git ls-remote --tags --refs "$$repo" 'v*' 2>/dev/null \
				| awk -F/ '{print $$NF}' \
				| grep -E '^v[0-9]+\.[0-9]+\.[0-9]+$$' \
				| sort -V | tail -n 1) || true; \
			[ -n "$$ref" ] || offline_ok "could not resolve the latest version tag from $$repo"; \
		fi; \
		if printf '%s\n' "$$ref" | grep -Eq '^v[0-9]+\.[0-9]+\.[0-9]+$$'; then \
			url="$$repo/archive/refs/tags/$$ref.tar.gz"; \
		elif [ "$$ref" = latest ] || [ "$$ref" = main ]; then \
			url="$$repo/archive/refs/heads/$$ref.tar.gz"; \
		else \
			url="$$repo/archive/$$ref.tar.gz"; \
		fi; \
	fi; \
	tmp=$$(mktemp -d); \
	lock=_extensions/.evidence-install.lock; \
	backup="$$tmp/previous"; \
	lock_held=0; \
	installing=; \
	cleanup() { \
		status=$$?; \
		trap - 0 1 2 15; \
		if [ "$$status" -ne 0 ]; then \
			for ext in $$installing; do rm -rf "_extensions/$$ext"; done; \
			for ext in $$exts; do \
				if [ -e "$$backup/$$ext" ] || [ -L "$$backup/$$ext" ]; then \
					rm -rf "_extensions/$$ext"; \
					mv "$$backup/$$ext" "_extensions/$$ext" || status=1; \
				fi; \
			done; \
		fi; \
		[ "$$lock_held" -eq 0 ] || rmdir "$$lock" 2>/dev/null || true; \
		rm -rf "$$tmp"; \
		exit "$$status"; \
	}; \
	trap cleanup 0; \
	trap 'exit 1' 1 2 15; \
	if [ -n "$$archive" ]; then \
		[ -s "$$archive" ] || offline_ok "managed source archive is missing"; \
		cp "$$archive" "$$tmp/asta-plugins.tar.gz"; \
	else \
		curl -fsSL "$$url" -o "$$tmp/asta-plugins.tar.gz" || offline_ok "download from $$url failed"; \
	fi; \
	tar -xzf "$$tmp/asta-plugins.tar.gz" -C "$$tmp"; \
	mkdir "$$tmp/new" "$$backup"; \
	for ext in $$exts; do \
		source_dir=$$(find "$$tmp" -type d -path "*/plugins/asta-tools/skills/workspace/assets/_extensions/$$ext" -print -quit); \
		if [ -z "$$source_dir" ]; then \
			case " $$required_exts " in *" $$ext "*) \
				echo "$$ext extension not found in asta-plugins@$${ref:-$$url}; select a ref that supplies it before rendering this _quarto.yml" >&2; exit 1 ;; esac; \
			echo "workspace-assets: asta-plugins@$${ref:-$$url} has no $$ext extension; skipping" >&2; continue; \
		fi; \
		cp -R "$$source_dir" "$$tmp/new/$$ext"; \
		if [ "$$ext" = asta-theme ]; then \
			for file in $$theme_files; do \
				asset="$$tmp/new/$$ext/$$file"; \
				if [ ! -f "$$asset" ] || [ -L "$$asset" ] || [ ! -s "$$asset" ]; then \
					echo "workspace-assets: incomplete asta-theme in asta-plugins@$${ref:-$$url}: $$file must be a nonempty regular file; keeping existing extensions" >&2; exit 1; \
				fi; \
			done; \
		fi; \
	done; \
	mkdir -p _extensions; \
	mkdir "$$lock" 2>/dev/null || { echo "another workspace-assets install is in progress" >&2; exit 1; }; \
	lock_held=1; \
	for ext in $$exts; do \
		[ -d "$$tmp/new/$$ext" ] || continue; \
		if [ -e "_extensions/$$ext" ] || [ -L "_extensions/$$ext" ]; then \
			mv "_extensions/$$ext" "$$backup/$$ext"; \
		fi; \
		installing="$$installing $$ext"; \
		mv "$$tmp/new/$$ext" "_extensions/$$ext"; \
		echo "workspace-assets: installed $$ext extension from asta-plugins@$${ref:-$$url}"; \
	done

workspace-viewers:
	@set -eu; \
	[ '$(subst ','"'"',$(ASTA_WORKSPACE_VIEWERS))' != 0 ] || exit 0; \
	discovery='$(subst ','"'"',$(firstword $(wildcard scripts/paper-discovery.py $(ASTA_WORKSPACE_SCRIPTS)/paper-discovery.py)))'; \
	viewer='$(subst ','"'"',$(firstword $(wildcard scripts/paper-viewer.py $(ASTA_WORKSPACE_SCRIPTS)/paper-viewer.py)))'; \
	if [ -z "$$discovery" ] || [ -z "$$viewer" ]; then \
		if find . -type d \( -name node_modules -o -name _site -o -name .asta -o -name .git -o -name venv -o -name .venv -o -name paper-previews \) -prune -o -type f -name main.tex -print -quit | grep -q .; then \
			[ -n "$$discovery" ] || echo "workspace-viewers: missing paper-discovery.py" >&2; \
			[ -n "$$viewer" ] || echo "workspace-viewers: missing paper-viewer.py" >&2; \
			echo "workspace-viewers: update the Asta CLI and run 'asta workspace sync --refresh --require-scripts' before removing existing viewer pages" >&2; \
		fi; exit 0; \
	fi; \
	python='$(subst ','"'"',$(PYTHON))'; \
	if ! command -v "$$python" >/dev/null 2>&1; then \
		echo "workspace-viewers: $$python is unavailable; keeping existing viewer pages" >&2; exit 0; \
	fi; \
	tmp=$$(mktemp); trap 'rm -f "$$tmp"' 0; \
	"$$python" "$$discovery" > "$$tmp"; \
	"$$python" "$$viewer" < "$$tmp"

preview: workspace-assets workspace-viewers
	quarto preview --no-browser

# Optional output override for callers that must leave the preview's _site alone,
# and an optional whitespace-separated page list (no spaces within filenames).
# The recipe marker declares page-list support. Keep it only in recipes that
# implement that contract; prerequisite output cannot declare this capability.
ASTA_WORKSPACE_RENDER_OUTPUT ?=
ASTA_WORKSPACE_RENDER_FILES ?=
render: workspace-assets workspace-viewers
	set -eu; \
	: asta-workspace-render-page-selection-v1; \
	set -f; \
	pages='$(subst ','"'"',$(value ASTA_WORKSPACE_RENDER_FILES))'; set -- $$pages; \
	if [ "$$#" -eq 0 ]; then \
		quarto render $(if $(value ASTA_WORKSPACE_RENDER_OUTPUT),--output-dir '$(subst ','"'"',$(value ASTA_WORKSPACE_RENDER_OUTPUT))'); \
	else \
		for page do \
			case "$$page" in /*|./*|../*) ;; *) page=./$$page;; esac; \
			quarto render "$$page" --no-clean $(if $(value ASTA_WORKSPACE_RENDER_OUTPUT),--output-dir '$(subst ','"'"',$(value ASTA_WORKSPACE_RENDER_OUTPUT))'); \
		done; \
	fi

# Compare the branch base with the working tree without rendering over the
# preview's _site/. Publish the comparison and its supporting render assets there. Older plain
# Quarto render recipes keep their prerequisites and get a temporary CLI adapter
# for page selection; custom recipes retain the full-site fallback. A changed deck's
# slides render as images when PYTHON has Playwright, as in the PR preview.
WHAT_CHANGED_BASE ?=
WHAT_CHANGED_FULL ?=
what-changed:
	@set -eu; \
	set -f; variables=; for flag in $$MAKEFLAGS; do case "$$flag" in --) break;; *=*) variables=1;; --*|*[!A-Za-z-]*) ;; -*) case "$$flag" in *n*) echo 'what-changed: dry run; no renders or worktrees created'; exit 0;; esac;; *) if [ -z "$$variables" ]; then case "$$flag" in *n*) echo 'what-changed: dry run; no renders or worktrees created'; exit 0;; esac; fi;; esac; done; set +f; \
	base='$(subst ','"'"',$(value WHAT_CHANGED_BASE))'; \
	source=$$base; \
	if [ -z "$$base" ]; then \
		upstream=$$(git symbolic-ref -q refs/remotes/origin/HEAD || true); \
		if [ -n "$$upstream" ]; then \
			base=$$(git merge-base HEAD "$$upstream" 2>/dev/null) || base=; \
			source=$$upstream; \
		fi; \
		if [ -z "$$base" ]; then \
			configured=$$(git config --get init.defaultBranch || true); \
			for branch in "$$configured" main master trunk; do \
				[ -n "$$branch" ] || continue; \
				source=refs/heads/$$branch; \
				base=$$(git merge-base HEAD "$$source" 2>/dev/null) && break || base=; \
			done; \
		fi; \
	fi; \
	[ -n "$$base" ] || { echo "what-changed: no base branch found; set WHAT_CHANGED_BASE=<ref>" >&2; exit 1; }; \
	base=$$(git rev-parse --verify --end-of-options "$$base^{commit}") || { echo "what-changed: invalid base; set WHAT_CHANGED_BASE=<ref>" >&2; exit 1; }; \
	label=$$(git rev-parse --short "$$base"); \
	prefix=$$(git rev-parse --show-prefix); \
	quarto=$$(command -v quarto) || { echo 'what-changed: quarto not found on PATH' >&2; exit 1; }; \
	makefile='$(subst ','"'"',$(firstword $(MAKEFILE_LIST)))'; \
	ignore_before=$$(git hash-object .gitignore 2>/dev/null || printf missing); \
	echo "what-changed: base $$source ($$base); running its make render" >&2; \
	tmp=; current=; publication=; assets_installed=; lock_held=; \
	cleanup() { \
		status=$$?; trap - 0; trap '' 1 2 15; \
		ignore_after=$$(git hash-object .gitignore 2>/dev/null || printf missing); \
		if [ "$$ignore_before" != "$$ignore_after" ]; then \
			echo 'what-changed: .gitignore changed during the build (Quarto may add cache entries); review that edit. Page selection used the source changes from before the build.' >&2; \
		fi; \
		if [ -n "$$publication" ]; then \
			if [ -e "$$publication/old" ] || [ -L "$$publication/old" ]; then \
				rm -rf _site/what-changed-assets; \
				mv "$$publication/old" _site/what-changed-assets || { echo "what-changed: could not restore previous assets from $$publication/old" >&2; exit 1; }; \
			elif [ -n "$$assets_installed" ]; then rm -rf _site/what-changed-assets; fi; \
			rm -rf "$$publication"; \
		fi; \
		[ -z "$$current" ] || rm -rf "$$current"; \
		if [ -n "$$tmp" ] && [ -d "$$tmp/base" ] && ! git worktree remove --force "$$tmp/base" >/dev/null 2>&1; then \
			echo "what-changed: cleanup failed; remove the worktree at $$tmp/base manually" >&2; exit 1; \
		fi; \
		[ -z "$$tmp" ] || rm -rf "$$tmp"; \
		[ -z "$$lock_held" ] || rmdir .asta/cache/what-changed.lock; exit "$$status"; \
	}; \
	trap cleanup 0; \
	trap 'exit 129' 1; trap 'exit 130' 2; trap 'exit 143' 15; \
	mkdir -p .asta/cache; \
	mkdir .asta/cache/what-changed.lock 2>/dev/null || { echo 'what-changed: another comparison is in progress; after an uncatchable interruption, remove .asta/cache/what-changed.lock before retrying' >&2; exit 1; }; \
	lock_held=1; \
	tmp=$$(mktemp -d); \
	(cd "$$(git rev-parse --show-toplevel)" && { git diff --name-only --no-renames "$$base" -- && git ls-files --others --exclude-standard; } | sort -u) > "$$tmp/changed"; \
	current=$$(mktemp -d .asta/cache/what-changed.XXXXXX); \
	mkdir "$$tmp/current-bin"; \
	printf '%s\n' '#!/bin/sh' 'set -eu' \
		'if [ "$${1:-}" = render ]; then' \
		'  found=; previous=; for argument do' \
		'    if [ "$$previous" = --output-dir ]; then found=$$argument; fi' \
		'    previous=$$argument' '  done' \
		'  [ "$$found" = "$$ASTA_WHAT_CHANGED_OUTPUT" ] || { echo "what-changed: current quarto render must honour ASTA_WORKSPACE_RENDER_OUTPUT; refusing to overwrite the live preview" >&2; exit 1; }' \
		'fi' \
		'[ "$${ASTA_WHAT_CHANGED_PROBE:-}" != 1 ] || exit 0' \
		'exec "$$ASTA_WHAT_CHANGED_QUARTO" "$$@"' > "$$tmp/current-bin/quarto"; \
	chmod +x "$$tmp/current-bin/quarto"; \
	: 'Recursive dry runs may execute recursive/+ lines; guard Quarto before probing and never render during the probe'; \
	current_probe=$$(PATH="$$tmp/current-bin:$$PATH" ASTA_WHAT_CHANGED_QUARTO="$$quarto" ASTA_WHAT_CHANGED_OUTPUT="$$current" ASTA_WHAT_CHANGED_PROBE=1 \
		$(MAKE) -f "$$makefile" -n render ASTA_WORKSPACE_RENDER_OUTPUT="$$current" ASTA_WORKSPACE_RENDER_FILES=asta-what-changed-page-probe.qmd 2>/dev/null) || current_probe=; \
	printf '%s\n' "$$current_probe" | grep -Fq -- "$$current" || { \
		echo "what-changed: current render recipe must honour ASTA_WORKSPACE_RENDER_OUTPUT; refusing to overwrite the live preview" >&2; exit 1; }; \
	git worktree add -q --detach "$$tmp/base" "$$base"; \
	dir="$$tmp/base/$$prefix"; \
	for version in current base; do \
		project=.; [ "$$version" != base ] || project=$$dir; \
		if [ ! -f "$$project/_quarto.yml" ] && [ ! -f "$$project/_quarto.yaml" ]; then \
			echo "what-changed: missing Quarto project configuration at $$project; both versions must define a site with project.output-dir=_site" >&2; exit 1; \
		fi; \
		if ! "$$quarto" inspect "$$project" > "$$tmp/inspect.json" 2> "$$tmp/inspect.err"; then \
			echo "what-changed: preparing $$version workspace assets before retrying project inspection" >&2; \
			if [ "$$version" = base ]; then \
				$(MAKE) -C "$$dir" workspace-assets >&2; \
			else $(MAKE) -f "$$makefile" workspace-assets >&2; fi \
				|| { cat "$$tmp/inspect.err" >&2; echo "what-changed: could not prepare $$version workspace assets for inspection" >&2; exit 1; }; \
			"$$quarto" inspect "$$project" > "$$tmp/inspect.json" 2> "$$tmp/inspect.err" || { cat "$$tmp/inspect.err" >&2; echo "what-changed: could not inspect project configuration at $$project" >&2; exit 1; }; \
		fi; \
		cat "$$tmp/inspect.err" >&2; \
		$(PYTHON) -c 'import json, pathlib, sys; data = json.load(open(sys.argv[1])); site = data.get("config", {}).get("project", {}).get("output-dir"); site_ok = isinstance(site, str) and pathlib.PurePosixPath(site).parts == ("_site",); root = pathlib.Path(sys.argv[2]).resolve(); inputs = data.get("files", {}).get("input", []); paths = [(root / p).resolve() for p in inputs]; print("\n".join(str(p.relative_to(root)) for p in paths if p.is_relative_to(root))); sys.exit(0 if site_ok else "what-changed: requires project.output-dir=_site in both versions; found " + repr(site) + " at " + sys.argv[2])' "$$tmp/inspect.json" "$$project" > "$$tmp/$$version-inputs"; \
	done; \
	files=; basefiles=; partial=; legacy=; \
	if [ -z '$(subst ','"'"',$(value WHAT_CHANGED_FULL))' ]; then \
		if [ -s "$$tmp/changed" ]; then \
			partial=1; \
			while IFS= read -r path; do \
				case "$$path" in "$$prefix"*) rel=$${path#"$$prefix"};; *) partial=; break;; esac; \
				if printf '%s\n' "$$rel" | grep -q '[^A-Za-z0-9._/+@-]'; then partial=; break; fi; \
				case "/$$rel" in */_*|*/.*) partial=; break;; esac; \
				case "$$rel" in *.qmd|*.md|*.ipynb|*.Rmd) ;; *) partial=; break;; esac; \
				[ -f "$$rel" ] || { partial=; break; }; \
				grep -Fxq -- "$$rel" "$$tmp/current-inputs" || { partial=; break; }; \
				files="$$files ./$$rel"; \
				if [ -f "$$dir/$$rel" ]; then \
					grep -Fxq -- "$$rel" "$$tmp/base-inputs" || { partial=; break; }; \
					basefiles="$$basefiles ./$$rel"; \
				fi; \
			done < "$$tmp/changed"; \
		fi; \
		if [ -n "$$partial" ]; then \
			printf '%s\n' "$$current_probe" | grep -Eq '^[[:space:]]*: asta-workspace-render-page-selection-v1;' && \
				printf '%s\n' "$$current_probe" | grep -q asta-what-changed-page-probe || partial=; \
		fi; \
		if [ -n "$$partial" ]; then \
			probe=$$($(MAKE) -n -C "$$dir" render ASTA_WORKSPACE_RENDER_OUTPUT= ASTA_WORKSPACE_RENDER_FILES=asta-what-changed-probe.qmd 2>/dev/null) || probe=; \
			if printf '%s\n' "$$probe" | grep -Eq '^[[:space:]]*: asta-workspace-render-page-selection-v1;' && \
				printf '%s\n' "$$probe" | grep -q asta-what-changed-probe; then :; \
			elif printf '%s\n' "$$probe" | grep -Eq '^[[:space:]]*quarto render[[:space:]]*$$'; then legacy=1; \
			else partial=; fi; \
		fi; \
	fi; \
	current_render() { \
		PATH="$$tmp/current-bin:$$PATH" ASTA_WHAT_CHANGED_QUARTO="$$quarto" ASTA_WHAT_CHANGED_OUTPUT="$$current" \
			$(MAKE) -f "$$makefile" render ASTA_WORKSPACE_RENDER_OUTPUT="$$current" ASTA_WORKSPACE_RENDER_FILES="$$1" >&2; \
	}; \
	if [ -n "$$partial" ]; then \
		echo "what-changed: only pages changed; rendering$$files (WHAT_CHANGED_FULL=1 renders the whole site)" >&2; \
		mkdir -p "$$dir/_site"; \
		if [ -n "$$legacy" ]; then \
			mkdir "$$tmp/bin"; \
			printf '%s\n' '#!/bin/sh' 'set -eu' \
				'if [ "$${1:-}" != render ]; then exec "$$ASTA_WHAT_CHANGED_QUARTO" "$$@"; fi' \
				'shift' 'for page in $$ASTA_WHAT_CHANGED_PAGES; do' \
				'  "$$ASTA_WHAT_CHANGED_QUARTO" render "$$page" --no-clean "$$@"' 'done' > "$$tmp/bin/quarto"; \
			chmod +x "$$tmp/bin/quarto"; \
		fi; \
		if [ -n "$$basefiles" ]; then \
			if [ -n "$$legacy" ]; then \
				PATH="$$tmp/bin:$$PATH" ASTA_WHAT_CHANGED_QUARTO="$$quarto" ASTA_WHAT_CHANGED_PAGES="$$basefiles" \
					$(MAKE) -C "$$dir" render ASTA_WORKSPACE_RENDER_OUTPUT= ASTA_WORKSPACE_RENDER_FILES= >&2; \
			else $(MAKE) -C "$$dir" render ASTA_WORKSPACE_RENDER_OUTPUT= ASTA_WORKSPACE_RENDER_FILES="$$basefiles" >&2; fi \
				|| { echo "what-changed: base render failed; restore its required inputs or choose WHAT_CHANGED_BASE=<ref>" >&2; exit 1; }; \
		fi; \
		current_render "$$files"; \
	else \
		$(MAKE) -C "$$dir" render ASTA_WORKSPACE_RENDER_OUTPUT= ASTA_WORKSPACE_RENDER_FILES= >&2 || { echo "what-changed: base render failed; restore its required inputs or choose WHAT_CHANGED_BASE=<ref>" >&2; exit 1; }; \
		current_render ""; \
	fi; \
	find "$$current" -type f -name '*.html' -print -quit | grep -q . || { \
		echo "what-changed: current render produced no HTML in the temporary output; check the render recipe and HTML format" >&2; exit 1; }; \
	mkdir -p _site; \
	theme=; [ -z "$$partial" ] || theme="--theme-root=_site"; \
	decks=; ! grep -rlq --include='*.html' 'class="reveal' "$$current" || decks="--render-decks=$$current/what-changed-decks"; \
	if [ -n "$$decks" ] && [ ! -f '$(dir $(call workspace_script,what-changed.py))deck-review.py' ]; then \
		echo "what-changed: showing slides as text: deck-review.py is missing beside $(call workspace_script,what-changed.py); upgrade the Asta CLI and run 'asta workspace sync --refresh'" >&2; \
	fi; \
	if [ -n "$$decks" ] && { [ -e "$$current/what-changed-decks" ] || [ -L "$$current/what-changed-decks" ]; }; then \
		echo "what-changed: replacing generated deck-review images in what-changed-decks" >&2; \
	fi; \
	$(PYTHON) $(call workspace_script,what-changed.py) --old "$$dir/_site" --new "$$current" \
		--out "$$tmp/what-changed.html" --title "Changes since $$label" $$theme --theme-url-prefix=what-changed-assets/ --reserved-local-output \
		$$decks --render-decks-url=what-changed-assets/what-changed-decks; \
	publication=$$(mktemp -d _site/.what-changed-publish.XXXXXX); \
	mv "$$current" "$$publication/new"; current=; \
	mv "$$tmp/what-changed.html" "$$publication/report.html"; \
	trap '' 1 2 15; \
	if [ -e _site/what-changed-assets ] || [ -L _site/what-changed-assets ]; then \
		mv _site/what-changed-assets "$$publication/old"; \
	fi; \
	mv "$$publication/new" _site/what-changed-assets; assets_installed=1; \
	mv "$$publication/report.html" _site/what-changed.html; \
	completed=$$publication; publication=; assets_installed=; rm -rf "$$completed"; \
	trap 'exit 129' 1; trap 'exit 130' 2; trap 'exit 143' 15; \
	echo "what-changed: wrote _site/what-changed.html; open /what-changed.html in make preview (rerun after edits or a preview rebuild)"

# Run the same quality gates CI runs, in one place so local and CI can't
# drift. CI's docs workflow calls this target — when a project grows a new
# gate, add it here (or as a prerequisite target), never as an inline workflow
# step. The render/validate script comes from the workspace cache unless the
# project supplies scripts/quarto-check.sh.
# Projects can require this marker so a custom rules file cannot make their
# `check` target pass without the shared quality gate.
ASTA_WORKSPACE_CHECK := 1
check: workspace-shared-check
workspace-shared-check: workspace-assets workspace-viewers
	sh $(call workspace_script,quarto-check.sh)

clean:
	rm -rf _site .quarto

# Open VS Code attached to the devcontainer.
dev:
	@code --folder-uri "vscode-remote://dev-container+$$(printf '%s' "$$(pwd)" | xxd -p | tr -d '\n')/workspaces/$$(basename "$$(pwd)")"

# Print the deployed URL the user can visit.
# On main: the GitHub Pages root. On a feature branch: the PR's preview URL.
deployed-url:
	@branch=$$(git rev-parse --abbrev-ref HEAD); \
	if [ "$$branch" = "main" ]; then \
		gh repo view --json owner,name -q '"https://" + .owner.login + ".github.io/" + .name + "/"'; \
	else \
		pr=$$(gh pr view --json url -q .url 2>/dev/null) || { echo "No PR for $$branch yet — push the branch and open a PR first." >&2; exit 1; }; \
		echo "PR: $$pr"; \
		preview=$$(gh pr view --json comments -q '.comments[] | select(.body | test("Preview:")) | .body' 2>/dev/null | tail -1); \
		[ -n "$$preview" ] && echo "$$preview" || echo "(Preview URL not posted yet — CI may still be running.)"; \
	fi

# Preview readiness, for automated callers that report a preview link: mark the
# Pages tip and latest docs run before pushing, then block until this push's
# deployment is live.
preview-baseline:
	sh $(call workspace_script,wait-for-preview.sh) baseline

preview-ready:
	sh $(call workspace_script,wait-for-preview.sh) wait

# The paper's latexmkrc selects its engine and bibliography search path.
PAPER_DIR ?= paper
PAPER_LATEXMK_FLAGS ?= -f
.PHONY: paper paper-clean
# Main document: main.tex, else the single .tex file containing \documentclass.
PAPER_MAIN = cd "$(PAPER_DIR)" 2>/dev/null || { echo "No paper directory $(PAPER_DIR)" >&2; exit 1; }; \
	if [ -f main.tex ] && [ ! -L main.tex ]; then main=main.tex; else \
	main=; count=0; for file in *.tex .*.tex; do \
	if [ -f "$$file" ] && [ ! -L "$$file" ] && python3 -c 'import pathlib,re,sys; sys.exit(not re.search(r"(?m)^[^\n]*(?<!\\)(?:\\\\)*\\documentclass\s*[\[{]", re.sub(r"(?<!\\)((?:\\\\)*)%[^\n]*", r"\1", pathlib.Path(sys.argv[1]).read_text(errors="replace"))))' "$$file"; then main=$$file; count=$$((count+1)); fi; done; \
	[ $$count -eq 1 ] || { echo "$(PAPER_DIR): add main.tex, or keep exactly one .tex file with documentclass" >&2; exit 1; }; fi
paper:
	@$(PAPER_MAIN); printf 'latexmk -synctex=1 -interaction=nonstopmode $(PAPER_LATEXMK_FLAGS) -file-line-error -outdir=build "%s"\n' "./$$main"; latexmk -synctex=1 -interaction=nonstopmode $(PAPER_LATEXMK_FLAGS) -file-line-error -outdir=build "./$$main"

paper-clean:
	@$(PAPER_MAIN); printf 'latexmk -C -outdir=build "%s"\n' "./$$main"; latexmk -C -outdir=build "./$$main"
