FROM public.ecr.aws/docker/library/node:22-slim AS asta

RUN apt-get update && apt-get install -y --no-install-recommends git curl ca-certificates make python3 \
    && rm -rf /var/lib/apt/lists/*

COPY image/skills-cli/package.json image/skills-cli/package-lock.json /opt/skills-cli/
RUN npm ci --prefix /opt/skills-cli --omit=dev --engine-strict \
    && npm cache clean --force \
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
#   skills add /opt/asta-plugins                      (any agent)

# Codespaces runs this on create, alongside the project's own postCreateCommand,
# so project devcontainer.json files carry no auth setup.
COPY docker/asta-persist-auth /usr/local/bin/asta-persist-auth
LABEL devcontainer.metadata='[{"postCreateCommand":"asta-persist-auth"}]'

WORKDIR /app

# Published as ghcr.io/allenai/asta:<tag>-tex for workspaces with a paper/.
# The CI paper preview runs inside this image, so local and CI builds agree.
FROM asta AS tex
# Debian's latexml depends on Debian's base LaTeX; the TeX Live symlinks in
# /usr/local/bin take precedence over it on PATH.
RUN apt-get update && apt-get install -y --no-install-recommends \
      latexml poppler-utils perl ghostscript fontconfig python3-pygments \
    && rm -rf /var/lib/apt/lists/*
# Upstream TeX Live 2026, full scheme without docs/sources: Overleaf's default
# for new projects.
COPY --from=mirror.gcr.io/texlive/texlive:latest-full@sha256:a7ae4dfa9d521b5db14446872fa488b839021d1f604d0a3c74461784895f2a67 \
    /usr/local/texlive /usr/local/texlive
# The upstream image links into /usr/bin, where Debian's TeX binaries already
# sit and win; link into /usr/local/bin instead.
RUN tlmgr=$(echo /usr/local/texlive/2026/bin/*/tlmgr) \
    && "$tlmgr" option sys_bin /usr/local/bin \
    && "$tlmgr" option sys_man /usr/local/share/man \
    && "$tlmgr" option sys_info /usr/local/share/info \
    && "$tlmgr" path add \
    && pdflatex --version | grep -q 'TeX Live 2026' \
    && test "$(command -v pdflatex)" = /usr/local/bin/pdflatex \
    && latexmk --version && latexdiff --version && biber --version
# LaTeXML ships styles in Debian's tree, outside upstream TeX Live's search path.
RUN local_tree=$(kpsewhich -var-value=TEXMFLOCAL) \
    && mkdir -p "$local_tree/tex/latex" \
    && cp -r /usr/share/texmf/tex/latex/latexml "$local_tree/tex/latex/" \
    && mktexlsr "$local_tree" \
    && kpsewhich latexml.sty
# Fontconfig settings outside the copied TeX tree expose bundled fonts by name.
RUN cp "$(kpsewhich -var-value=TEXMFSYSVAR)/fonts/conf/texlive-fontconfig.conf" \
      /etc/fonts/conf.d/09-texlive-fonts.conf \
    && fc-cache -fs \
    && fc-match -f '%{file}' 'TeX Gyre Termes' | grep -q '^/usr/local/texlive/2026/'
# System defaults load before user and project latexmkrc files.
COPY docker/latexmkrc /etc/LatexMk
ENV LATEXMKRCSYS=/etc/LatexMk
# Ship the extension and editor defaults only with TeX. This replaces the
# parent metadata label, so it repeats the auth hook.
LABEL devcontainer.metadata='[{"postCreateCommand":"asta-persist-auth"},{"customizations":{"vscode":{"extensions":["james-yu.latex-workshop"],"settings":{"latex-workshop.latex.autoBuild.run":"onSave","latex-workshop.view.pdf.viewer":"tab","latex-workshop.latex.outDir":"%DIR%/build","latex-workshop.latex.recipes":[{"name":"latexmk","tools":["latexmk"]}],"latex-workshop.latex.tools":[{"name":"latexmk","command":"latexmk","args":["-synctex=1","-interaction=nonstopmode","-halt-on-error","-file-line-error","-outdir=%OUTDIR%","%DOC%"]}]}}}}]'

# A plain `docker build .` still produces the slim image.
FROM asta
