# Overleaf publication recognition

`asta workspace overleaf publish` leaves the workspace sync record unchanged.
Its Overleaf commit subject names the full reviewed workspace commit. `pull`
uses a recognized publication as a merge base only when the source belongs to
the local checkout's history or the committed paper already matches it. Older
checkouts search earlier publications and finally use the recorded pull.

## Review and replay checks

A marker counts only when its workspace source is an ancestor of the fetched
`origin` default-branch tip, its paper bytes exactly match the Overleaf commit,
and its sync record names this project. CLI arguments and loaded sync records
normalize equivalent project URL spellings before recognition.

The source's recorded Overleaf pull anchors an uninterrupted first-parent chain.
Each marker must name a matching reviewed workspace source with that same anchor;
consecutive workspace sources must descend from one another. This rejects a
replayed older publication and a cherry-picked marker over an ordinary edit.
Content equality alone cannot identify a publication: a collaborator's revert to
older reviewed content still needs pull and review.

Publish checks the Overleaf tip first, refusing an ordinary edit without scanning
older publications. A publication tip verifies its prior chain. Pull considers
newest candidates first. Publication results, including invalid records, and
consecutive source-ancestry results are cached within the command. Chain walks
still read first-parent logs for each candidate, so history traversal can grow
with the number of publications since the recorded pull.

## Fetching and failures

The review gate fetches the advertised default branch into a temporary ref,
preserving existing branch refs and `FETCH_HEAD`. Normal fetches preserve shallow
history. A real sync can complete it when a publication source or ancestry needs
verification, printing a notice before the permanent change. Dry-run refuses
instead, preserving shallow boundaries.

Completion fetches the branch ref discovered for the gate rather than a raw
ancestor SHA, supporting servers that refuse raw-SHA requests. Verification
continues to use the original reviewed tip even if the branch advances or the
remote's default-branch symref changes during completion.

Pull falls back to the recorded sync with a warning only for origin-discovery or
transport failures. Publication file reads, local Git failures and gate-ref
resolution failures propagate sanitized errors before copying. Missing objects
and non-ancestry are expected negative verification results; other Git exit
statuses are errors. Publish reports origin-access guidance and nothing pushed
when transport fails.

`--expected-commit` accepts a full SHA-1 or SHA-256 ID, including uppercase input.
It requires the exact checkout and fetched default tip, then checks the
advertised branch and tip immediately before push. GitHub and Overleaf have no
shared transaction; a merge after this final check can still race with the push.

## Hosted compatibility evidence

The [hosted check](https://github.com/allenai/asta-plugins/pull/204#issuecomment-6134939707)
confirmed two CLI publication subjects in a fresh clone with a subsequent web
edit. Automated round-trip tests use a local bare remote. A bridge that rewrites
the subject or inserts an ordinary commit requires another pull and review,
even when paper bytes match a reviewed revision. No content-only fallback or
extra sync-record publication is used.

New publications use full commit IDs. Legacy abbreviated IDs remain best-effort
and must resolve unambiguously.
