FROM node:22-slim AS asta

RUN apt-get update && apt-get install -y --no-install-recommends git curl ca-certificates make python3 \
    && rm -rf /var/lib/apt/lists/*

COPY image/skills-cli/package.json image/skills-cli/package-lock.json /opt/skills-cli/
RUN npm ci --prefix /opt/skills-cli --omit=dev \
    && ln -s /opt/skills-cli/node_modules/.bin/skills /usr/local/bin/skills

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

# Codespaces runs this on create, alongside the project's own postCreateCommand,
# so project devcontainer.json files carry no auth setup.
COPY docker/asta-persist-auth /usr/local/bin/asta-persist-auth
LABEL devcontainer.metadata='[{"postCreateCommand":"asta-persist-auth"}]'

WORKDIR /app

# Published as ghcr.io/allenai/asta:<tag>-tex for workspaces with a paper/.
# Match the paper preview's TeX packages so local and CI builds agree.
FROM asta AS tex
RUN apt-get update && apt-get install -y --no-install-recommends \
      latexmk latexdiff latexml poppler-utils texlive-latex-base \
      texlive-latex-recommended texlive-latex-extra \
      texlive-fonts-recommended texlive-bibtex-extra \
      texlive-luatex texlive-xetex texlive-publishers \
      texlive-science texlive-pictures texlive-plain-generic biber \
    && rm -rf /var/lib/apt/lists/*
# Dev containers merge this into devcontainer.json, so LaTeX Workshop
# arrives with TeX and Quarto-only projects never get it. Replaces the parent
# label, so it repeats the auth hook.
LABEL devcontainer.metadata='[{"postCreateCommand":"asta-persist-auth"},{"customizations":{"vscode":{"extensions":["james-yu.latex-workshop"]}}}]'

# A plain `docker build .` still produces the slim image.
FROM asta
