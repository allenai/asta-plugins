.PHONY: help install test test-unit test-integration test-coverage lint format format-check clean build build-plugins publish publish-test push-version-tag version set-version check-plugins docker docker-test docker-test-skills docker-claude-asta docker-claude-asta-preview docker-codex-asta docker-codex-asta-preview

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
	@echo "Claude Code marketplace:"
	@echo "  build-plugins    Regenerate plugins/ from skills/"
	@echo "  check-plugins    Verify plugins/ is up to date"
	@echo ""
	@echo "Docker:"
	@echo "  docker           Build Docker image"
	@echo "  docker-test         Build and smoke-test Docker image"
	@echo "  docker-test-skills     Test skill discovery in Docker image"
	@echo "  docker-claude-asta          Start container with Claude Code + asta skills"
	@echo "  docker-claude-asta-preview  Start container with Claude Code + asta-preview skills"
	@echo "  docker-codex-asta           Start container with Codex CLI + asta skills"
	@echo "  docker-codex-asta-preview   Start container with Codex CLI + asta-preview skills"
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
test:
	uv run --extra test pytest -v

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

# Generate Claude Code plugin packages from skills/
build-plugins:
	./scripts/build-plugins.sh

# Verify plugins/ matches skills/ (used in CI)
check-plugins:
	@./scripts/build-plugins.sh > /dev/null
	@if ! git diff --quiet plugins/; then \
		echo "Error: plugins/ is out of date. Run 'make build-plugins' and commit."; \
		git diff --stat plugins/; \
		exit 1; \
	fi
	@echo "plugins/ is up to date"

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
	git tag v$$VERSION && \
	git push origin v$$VERSION && \
	echo "Pushed tag v$$VERSION"

# Show current version
version:
	@uv run python scripts/manage-version.py show

# Build Docker image
docker:
	docker build -t asta:latest .

# Build and smoke-test Docker image
docker-test: docker
	docker run --rm asta:latest sh -c '\
		set -e; \
		asta --version; \
		asta --help >/dev/null; \
		asta literature --help >/dev/null; \
		asta literature find --help >/dev/null; \
		asta auth login --help >/dev/null; \
		asta auth print-token --help >/dev/null; \
		quarto --version; \
		test -d /opt/asta-plugins/skills; \
		count=$$(find /opt/asta-plugins/skills -mindepth 1 -maxdepth 1 -type d | wc -l); \
		test "$$count" -ge 2; \
		for d in /opt/asta-plugins/skills/*/; do \
			test -f "$$d/SKILL.md" || { echo "Missing SKILL.md in $$d"; exit 1; }; \
		done; \
		test -f /opt/asta-plugins/.claude-plugin/marketplace.json; \
		echo "All smoke tests passed"'

# Test skill discovery in Docker image (npx skills add)
docker-test-skills: docker
	docker run --rm asta:latest sh -c '\
		set -e; \
		npx --yes skills@latest add /opt/asta-plugins --list; \
		npx --yes skills@latest add /opt/asta-plugins --list --all'

# Start container with Claude Code + asta skills
docker-claude-asta: docker
	docker run --rm -it -e ASTA_TOKEN -e ANTHROPIC_API_KEY asta:latest sh -c '\
		curl -fsSL https://claude.ai/install.sh | bash && \
		claude plugin marketplace add /opt/asta-plugins --scope user && \
		claude plugin install asta && \
		echo "Ready. Run: claude" && \
		exec bash'

# Start container with Claude Code + asta-preview skills
docker-claude-asta-preview: docker
	docker run --rm -it -e ASTA_TOKEN -e ANTHROPIC_API_KEY asta:latest sh -c '\
		curl -fsSL https://claude.ai/install.sh | bash && \
		claude plugin marketplace add /opt/asta-plugins --scope user && \
		claude plugin install asta-preview && \
		echo "Ready. Run: claude" && \
		exec bash'

# Start container with Codex CLI + asta skills
docker-codex-asta: docker
	docker run --rm -it -e ASTA_TOKEN -e OPENAI_API_KEY asta:latest sh -c '\
		npm install -g @openai/codex && \
		npx --yes skills@latest add /opt/asta-plugins -g --yes && \
		echo "Ready. Run: codex" && \
		exec bash'

# Start container with Codex CLI + asta-preview skills
docker-codex-asta-preview: docker
	docker run --rm -it -e ASTA_TOKEN -e OPENAI_API_KEY asta:latest sh -c '\
		npm install -g @openai/codex && \
		npx --yes skills@latest add /opt/asta-plugins -g --all --yes && \
		echo "Ready. Run: codex" && \
		exec bash'

# Quick check before commit
check: format-check lint test-unit
	@echo "All checks passed!"

# Full CI check
ci: format-check lint test check-plugins
	@echo "Full CI checks passed!"
