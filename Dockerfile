FROM node:20-slim

RUN apt-get update && apt-get install -y --no-install-recommends git curl ca-certificates \
    && rm -rf /var/lib/apt/lists/*

COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

# Install Quarto early so the layer is cached across source changes.
ARG QUARTO_VERSION=1.7.29
RUN ARCH=$(dpkg --print-architecture) \
    && curl -LO "https://github.com/quarto-dev/quarto-cli/releases/download/v${QUARTO_VERSION}/quarto-${QUARTO_VERSION}-linux-${ARCH}.deb" \
    && dpkg -i quarto-${QUARTO_VERSION}-linux-${ARCH}.deb \
    && rm quarto-${QUARTO_VERSION}-linux-${ARCH}.deb

COPY . /opt/asta-plugins
RUN uv tool install /opt/asta-plugins
ENV PATH="/root/.local/bin:$PATH"

# Source repo at /opt/asta-plugins — use with:
#   claude plugin marketplace add /opt/asta-plugins   (Claude Code)
#   npx skills add /opt/asta-plugins                  (any agent)

WORKDIR /app
