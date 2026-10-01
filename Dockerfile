FROM node:20-slim AS asta

RUN apt-get update && apt-get install -y --no-install-recommends git curl ca-certificates make python3 \
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

# Published as ghcr.io/allenai/asta:<tag>-tex for workspaces with a paper/.
# Keep this package list identical to the paper lane in
# workspace-quarto-site.yml so a paper that builds in CI builds in the container.
FROM asta AS tex
RUN apt-get update && apt-get install -y --no-install-recommends \
      latexmk latexdiff poppler-utils texlive-latex-base \
      texlive-latex-recommended texlive-latex-extra \
      texlive-fonts-recommended texlive-bibtex-extra \
      texlive-luatex texlive-xetex biber \
    && rm -rf /var/lib/apt/lists/*

# A plain `docker build .` still produces the slim image.
FROM asta
