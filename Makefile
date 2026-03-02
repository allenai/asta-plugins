.PHONY: help install test test-unit test-integration test-coverage lint format format-check clean build publish publish-test release version set-version

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
	@echo "  build            Build distribution packages"
	@echo "  publish          Publish to PyPI"
	@echo "  publish-test     Publish to TestPyPI"
	@echo "  set-version      Set version in all files (requires VERSION=x.y.z)"
	@echo "  release          Create GitHub release using current version"
	@echo "  version          Show current version"

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
	uvx ruff check .

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
	@if [ -z "$(VERSION)" ]; then \
		echo "Error: VERSION parameter is required. Usage: make set-version VERSION=x.y.z"; \
		exit 1; \
	fi; \
	echo "Setting version to $(VERSION) in all files..."; \
	echo "Updating src/asta/__init__.py..."; \
	sed -i.bak 's/__version__ = ".*"/__version__ = "$(VERSION)"/' src/asta/__init__.py && rm src/asta/__init__.py.bak; \
	echo "Updating pyproject.toml..."; \
	sed -i.bak 's/^version = ".*"/version = "$(VERSION)"/' pyproject.toml && rm pyproject.toml.bak; \
	echo "Updating .claude-plugin/plugin.json..."; \
	uv run python -c "import json; f = open('.claude-plugin/plugin.json', 'r'); data = json.load(f); f.close(); data['version'] = '$(VERSION)'; f = open('.claude-plugin/plugin.json', 'w'); json.dump(data, f, indent=2); f.write('\n'); f.close()"; \
	echo "Updating .claude-plugin/marketplace.json..."; \
	uv run python -c "import json; f = open('.claude-plugin/marketplace.json', 'r'); data = json.load(f); f.close(); data['plugins'][0]['version'] = '$(VERSION)'; f = open('.claude-plugin/marketplace.json', 'w'); json.dump(data, f, indent=2); f.write('\n'); f.close()"; \
	echo "Version updated to $(VERSION) in all files"; \
	echo "Review changes and commit with: git add -A && git commit -m 'chore: bump version to $(VERSION)'"

# Create GitHub release using version from code
release:
	@echo "Checking version consistency..."; \
	INIT_VERSION=$$(uv run python -c "from src.asta import __version__; print(__version__)"); \
	PYPROJECT_VERSION=$$(grep '^version = ' pyproject.toml | sed 's/version = "\(.*\)"/\1/'); \
	PLUGIN_VERSION=$$(uv run python -c "import json; f = open('.claude-plugin/plugin.json'); data = json.load(f); print(data['version'])"); \
	MARKETPLACE_VERSION=$$(uv run python -c "import json; f = open('.claude-plugin/marketplace.json'); data = json.load(f); print(data['plugins'][0]['version'])"); \
	if [ "$$INIT_VERSION" != "$$PYPROJECT_VERSION" ] || [ "$$INIT_VERSION" != "$$PLUGIN_VERSION" ] || [ "$$INIT_VERSION" != "$$MARKETPLACE_VERSION" ]; then \
		echo "Error: Version mismatch detected:"; \
		echo "  src/asta/__init__.py:              $$INIT_VERSION"; \
		echo "  pyproject.toml:                    $$PYPROJECT_VERSION"; \
		echo "  .claude-plugin/plugin.json:        $$PLUGIN_VERSION"; \
		echo "  .claude-plugin/marketplace.json:   $$MARKETPLACE_VERSION"; \
		echo ""; \
		echo "Run 'make set-version VERSION=x.y.z' to sync versions"; \
		exit 1; \
	fi; \
	VERSION=$$INIT_VERSION; \
	echo "Creating release v$$VERSION..."; \
	if git rev-parse v$$VERSION >/dev/null 2>&1; then \
		echo "Error: Tag v$$VERSION already exists"; \
		exit 1; \
	fi; \
	git tag v$$VERSION && \
	git push origin v$$VERSION && \
	echo "Release v$$VERSION created. Create GitHub release at:" && \
	echo "https://github.com/allenai/asta-plugins/releases/new?tag=v$$VERSION"

# Show current version
version:
	@uv run python -c "from src.asta import __version__; print(__version__)"

# Quick check before commit
check: format-check lint test-unit
	@echo "All checks passed!"

# Full CI check
ci: format-check lint test
	@echo "Full CI checks passed!"
