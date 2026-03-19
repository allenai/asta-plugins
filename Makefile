.PHONY: help install test test-unit test-integration test-coverage lint format format-check clean build build-plugins publish publish-test push-version-tag version set-version check-plugins

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
	@if [ -z "$(VERSION)" ]; then \
		echo "Error: VERSION parameter is required. Usage: make set-version VERSION=x.y.z"; \
		exit 1; \
	fi; \
	echo "Setting version to $(VERSION) in all files..."; \
	echo "Updating src/asta/__init__.py..."; \
	sed -i.bak 's/__version__ = ".*"/__version__ = "$(VERSION)"/' src/asta/__init__.py && rm src/asta/__init__.py.bak; \
	echo "Updating pyproject.toml..."; \
	sed -i.bak 's/^version = ".*"/version = "$(VERSION)"/' pyproject.toml && rm pyproject.toml.bak; \
	echo "Updating .claude-plugin/marketplace.json..."; \
	uv run python -c "import json; f = open('.claude-plugin/marketplace.json', 'r'); data = json.load(f); f.close(); [p.__setitem__('version', '$(VERSION)') for p in data['plugins']]; f = open('.claude-plugin/marketplace.json', 'w'); json.dump(data, f, indent=2); f.write('\n'); f.close()"; \
	echo "Version set to $(VERSION)"; \
	echo "Now run: make build-plugins"

# Create and push git tag using version from code
push-version-tag:
	@echo "Checking version consistency..."; \
	INIT_VERSION=$$(uv run python -c "from src.asta import __version__; print(__version__)"); \
	PYPROJECT_VERSION=$$(grep '^version = ' pyproject.toml | sed 's/version = "\(.*\)"/\1/'); \
	MARKETPLACE_VERSION=$$(uv run python -c "import json; data = json.load(open('.claude-plugin/marketplace.json')); print(data['plugins'][0]['version'])"); \
	if [ "$$INIT_VERSION" != "$$PYPROJECT_VERSION" ] || [ "$$INIT_VERSION" != "$$MARKETPLACE_VERSION" ]; then \
		echo "Error: Version mismatch detected:"; \
		echo "  src/asta/__init__.py:            $$INIT_VERSION"; \
		echo "  pyproject.toml:                  $$PYPROJECT_VERSION"; \
		echo "  .claude-plugin/marketplace.json: $$MARKETPLACE_VERSION"; \
		echo ""; \
		echo "Run 'make set-version VERSION=x.y.z' to sync versions"; \
		exit 1; \
	fi; \
	VERSION=$$INIT_VERSION; \
	git tag v$$VERSION && \
	git push origin v$$VERSION && \
	echo "Pushed tag v$$VERSION"

# Show current version
version:
	@uv run python -c "from src.asta import __version__; print(__version__)"

# Quick check before commit
check: format-check lint test-unit
	@echo "All checks passed!"

# Full CI check
ci: format-check lint test check-plugins
	@echo "Full CI checks passed!"
