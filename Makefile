.PHONY: help install test test-unit test-integration test-coverage lint format format-check clean build publish publish-test push-version-tag version set-version check-skills docker docker-test docker-test-skills docker-claude-asta docker-codex-asta

# Default target
help:
	@echo "Asta Plugins - Development Makefile"
	@echo ""
	@echo "Available targets:"
	@echo "  install          Install package with test dependencies"
	@echo "  test             Run all tests"
	@echo "  test-unit        Run unit tests only"
	@echo "  test-integration Run integration tests only"
	@echo "  test-coverage    Run tests with HTML coverage report"
	@echo "  lint             Check code style with ruff"
	@echo "  format           Auto-fix code formatting with ruff"
	@echo "  format-check     Check formatting without changes"
	@echo "  clean            Remove build artifacts and caches"
	@echo ""
	@echo "Docker:"
	@echo "  docker              Build Docker image"
	@echo "  docker-test         Build and smoke-test Docker image"
	@echo "  docker-test-skills  Test skill discovery in Docker image"
	@echo "  docker-claude-asta  Start container with Claude Code + asta-tools skills"
	@echo "  docker-codex-asta   Start container with Codex CLI + asta-tools skills"
	@echo ""
	@echo "Release:"
	@echo "  set-version      Set version in all files (requires VERSION=x.y.z)"
	@echo "  push-version-tag Create and push git tag using current version"
	@echo "  version          Show current version"
	@echo "  build            Build Python distribution packages"
	@echo "  publish          Publish to PyPI"
	@echo "  publish-test     Publish to TestPyPI"

# Install with test dependencies
install:
	uv sync --extra test

# Run all tests
test: test-plugins test-workspace

# Run unit tests only
test-unit:
	uv run --extra test pytest tests/test_client.py tests/test_cli.py -v

# Run integration tests only
test-integration:
	uv run --extra test pytest tests/test_integration.py tests/test_paper_finder.py -v

# Run tests with coverage
test-coverage:
	uv run --extra test pytest --cov=src/asta --cov-report=html --cov-report=term
	@echo "Coverage report generated in htmlcov/index.html"

# Check code style
lint:
	uvx ruff check .

# Fix formatting
format:
	uvx ruff format .
	uvx ruff check --fix .

# Check formatting without changes
format-check:
	uvx ruff format --check .

# Clean build artifacts
clean:
	rm -rf build/
	rm -rf dist/
	rm -rf *.egg-info
	rm -rf src/*.egg-info
	rm -rf .pytest_cache
	rm -rf .ruff_cache
	rm -rf htmlcov/
	rm -rf .coverage
	find . -type d -name __pycache__ -exec rm -rf {} +
	find . -type f -name '*.pyc' -delete

# Validate every SKILL.md against the Agent Skills spec (used in CI)
check-skills:
	@uvx --with pyyaml python scripts/validate-skills.py

# Build distribution packages
build: clean
	uv build

# Publish to PyPI
publish: build
	uv pip install twine
	uv run twine upload dist/*

# Publish to TestPyPI
publish-test: build
	uv pip install twine
	uv run twine upload --repository testpypi dist/*

# Set version in all files
set-version:
	@uv run python scripts/manage-version.py set $(VERSION)

# Create and push git tag using version from code
push-version-tag:
	@if ! uv run python scripts/manage-version.py check; then \
		exit 1; \
	fi; \
	VERSION=$$(uv run python scripts/manage-version.py show); \
	SHA=$$(git rev-parse HEAD); \
	git fetch -q origin main && \
	if ! git merge-base --is-ancestor $$SHA origin/main; then \
		echo "HEAD ($$SHA) is not on origin/main; check out the merged release commit" >&2; \
		exit 1; \
	fi; \
	test "$$(gh run list --workflow workspace-release-checks.yml --commit $$SHA --status success --json databaseId --jq length)" -gt 0 || { \
		echo "Run gh workflow run workspace-release-checks.yml --ref $$SHA and wait for it to pass before tagging" >&2; exit 1; \
	}; \
	scripts/wait-for-main-image.sh $$SHA && \
	git tag v$$VERSION && \
	git push origin v$$VERSION && \
	echo "Pushed tag v$$VERSION"

# Show current version
version:
	@uv run python scripts/manage-version.py show

# Build Docker image
docker:
	docker build $(DOCKER_BUILD_FLAGS) -t asta:latest .

# Build and smoke-test Docker image
docker-test: docker
	docker run --rm --entrypoint bash asta:latest /opt/asta-plugins/scripts/docker-smoke-test.sh

# Test skill discovery in Docker image (npx skills add)
docker-test-skills: docker
	docker run --rm --entrypoint bash asta:latest /opt/asta-plugins/scripts/docker-skill-discovery-test.sh

# Start container with Claude Code + asta-tools skills
docker-claude-asta: docker
	docker run --rm -it -e ASTA_TOKEN -e ANTHROPIC_API_KEY asta:latest sh -c '\
		curl -fsSL https://claude.ai/install.sh | bash && \
		claude plugin marketplace add /opt/asta-plugins --scope user && \
		claude plugin install asta-tools && \
		echo "Ready. Run: claude" && \
		exec bash'

# Start container with Codex CLI + asta-tools skills
docker-codex-asta: docker
	docker run --rm -it -e ASTA_TOKEN -e OPENAI_API_KEY asta:latest sh -c '\
		npm install -g @openai/codex && \
		skills add /opt/asta-plugins -g --yes && \
		echo "Ready. Run: codex" && \
		exec bash'

# Quick check before commit
check: format-check lint test-unit
	@echo "All checks passed!"

# Full CI check
ci: format-check lint test check-skills
	@echo "Full CI checks passed!"

# Workspace checks: ownership is tests/workspace; tools contains real render tests.
# CI supplies one shard per GitHub job. Local default runs the complete target.
WORKSPACE_PATHS := plugins/asta-tools/skills/workspace/ src/asta/commands/workspace src/asta/commands/overleaf examples/workspace tests/workspace/ tests/browser/ tests/dom/ .github/workflows/ scripts/ Makefile pyproject.toml uv.lock tests/conftest.py tests/_workspace_helpers.py src/asta/cli.py
export WORKSPACE_PATHS
WORKSPACE_SHARD ?= 0
WORKSPACE_SHARDS ?= 1
WORKSPACE_CASE ?=
PREVIEW_SITE ?= preview-site/pr-preview/pr-$(PR_NUMBER)
.PHONY: test-plugins test-workspace test-workspace-tools workspace-dom workspace-browser workspace-local workspace-compare workspace-demo workspace-scope check-workspace-tools

test-plugins:
	uv run --extra test pytest -v --ignore=tests/workspace

test-workspace:
	@for tool in make perl; do command -v $$tool >/dev/null || { echo "Missing required tool: $$tool" >&2; exit 1; }; done
	uv run --extra test python scripts/test-workspace.py $(WORKSPACE_SHARD) $(WORKSPACE_SHARDS)

check-workspace-tools: test-workspace-tools workspace-local

test-workspace-tools:
	@for tool in quarto make perl latexmk pdftotext; do command -v $$tool >/dev/null || { echo "Missing required tool: $$tool" >&2; exit 1; }; done
	uv run --extra test pytest -o addopts= -v tests/workspace/tools

workspace-scope:
	@python3 scripts/workspace-scope.py "$(BASE_SHA)"

workspace-dom:
	cd tests/dom && npm ci && npm test

workspace-demo:
	sh examples/workspace/scripts/check-paper.sh examples/workspace/_site
	python3 scripts/build-workspace-demo.py examples/workspace/_site/demo

workspace-local:
	bash scripts/check-workspace-local.sh

workspace-compare:
	cd examples/workspace && make workspace-assets
	PYTHONPATH=$(CURDIR)/src ASTA_WORKSPACE_CASE=$(WORKSPACE_CASE) uv run --no-project --with "$(CURDIR)" python tests/browser/workspace-differential.py tests/browser/artifacts/differential

workspace-browser:
	cd tests/browser && npm ci && npx playwright install --with-deps chromium
	python3 tests/browser/render-slides.py tests/browser/fixtures
	cd tests/browser && node workspace-slides.mjs "$(abspath $(PREVIEW_SITE))" artifacts
	cd tests/browser && npm test -- "$(abspath $(PREVIEW_SITE))" artifacts
	@if [ "$(PR_NUMBER)" != 0 ]; then cd tests/browser && node example-preview.mjs ../../preview-site artifacts; fi
	uv run --no-project --with playwright==1.64.1 python -m playwright install chromium
	uv run --no-project --with playwright==1.64.1 python tests/browser/deck-review.py "$(PREVIEW_SITE)" tests/browser/artifacts
	uv run --no-project --with playwright==1.64.1 python tests/browser/local-what-changed-demo.py --site "$(PREVIEW_SITE)/demo" tests/browser/artifacts
