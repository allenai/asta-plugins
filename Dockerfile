FROM ubuntu:24.04

COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

RUN apt-get update && apt-get install -y git curl nodejs npm && rm -rf /var/lib/apt/lists/*

COPY . /opt/asta-plugins
RUN uv tool install /opt/asta-plugins
ENV PATH="/root/.local/bin:$PATH"

# Install Quarto (used by experiment / literature-report rendering).
RUN ARCH=$(dpkg --print-architecture) \
    && QUARTO_VERSION=$(curl -s https://api.github.com/repos/quarto-dev/quarto-cli/releases/latest | grep -oP '"tag_name":\s*"v\K[^"]+') \
    && curl -LO "https://github.com/quarto-dev/quarto-cli/releases/download/v${QUARTO_VERSION}/quarto-${QUARTO_VERSION}-linux-${ARCH}.deb" \
    && dpkg -i quarto-${QUARTO_VERSION}-linux-${ARCH}.deb \
    && rm quarto-${QUARTO_VERSION}-linux-${ARCH}.deb

# Source repo at /opt/asta-plugins — use with:
#   claude plugin marketplace add /opt/asta-plugins   (Claude Code)
#   npx skills add /opt/asta-plugins                  (any agent)

WORKDIR /app
