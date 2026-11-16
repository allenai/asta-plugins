# CLI: your API key, our pipeline

You pay for it, through your own API key. It runs on this machine with `theorize` (Theorizer) and `auto-discovery` (AutoDS), which bake in our preferences. The model calls go to whoever your key is with. Nothing goes to Asta.

The workflow files are written for the CLI, so follow their commands as they are.

## Setup

```bash
theorize --version     # already the version you want? skip its install line
uv tool install --upgrade --python 3.13 asta-theorizer --with "pymupdf4llm<2"
uv tool install --upgrade --python 3.13 asta-autodiscovery
theorize doctor
```

Keep the pins: without `--python` the install fails on the newest Python, and `pymupdf4llm` 2.0 is an empty package, so PDFs would come in with no text. If `theorize` is already the version you were asked to use, don't reinstall it, because `--upgrade` would swap it for PyPI's.

## Keys

`theorize doctor` says which keys it reads, which are set, and how to set them. In short:

- OpenAI or Anthropic, for the models.
- Mistral, for reading PDFs. Without it, PDFs are converted on this machine and some text is lost.
- Semantic Scholar (`S2_API_KEY`), optional, to make searches faster.

AutoDS uses the key for its model's provider, such as `ANTHROPIC_API_KEY` for `anthropic/` models.

Never ask for a key in chat, because it would stay in the transcript. The person sets it, the way `theorize doctor` says.

## Commands

- **Papers:** `s2` finds them, and [S2 to asta-papers to Theorizer](../workflows/theory-generation/s2-papers.md) brings them in. `theorize papers import` adds the person's own.
- **AutoDS:** `auto-discovery`, as the `autodiscovery` skill's `workflows/local.md` says.
- **Theorizer:** [Theory generation](../workflows/theory-generation/README.md) has the whole sequence.
