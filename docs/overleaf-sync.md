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
newest candidates first. Publication results, including invalid records,
consecutive source-ancestry results, and structural chain checks are cached
within the command. Before completing workspace history, recognition checks
the available source's project
record, exact paper bytes, and the Overleaf chain's marker subjects and single
parents. If the source is absent, its recorded anchor cannot be inspected yet.
Checking that candidate against the local record would reject a valid
publication anchored by a newer pull reviewed elsewhere, and could overwrite
a subsequent local revert. Recognition therefore obtains the source before
checking its actual anchor.

A marker whose source is absent can still require history completion, even if
that source ultimately does not exist. An absent historical
publication and an invented ID cannot be distinguished from shallow local
objects alone. Dry-run reports unverifiable shallow history in that case,
without fetching it; it does not claim a collaborator edit is established.

Chain walks still read first-parent logs for each candidate, so history traversal
can grow with publications since the recorded pull. Pull always advances
`overleaf.json` to the current Overleaf head, including a verified publication
with no paper changes. Periodically pull, review and commit that checkpoint to
bound subsequent verification to publications after it. Publication continues
to leave the workspace record unchanged.

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
when transport fails. On fallback, pull compares candidate publication bytes
against the recorded files, the checkout, and the remote tip. If a publication
changed a file and its workspace and Overleaf copies now differ, pull refuses
before copying. The older base cannot distinguish an unseen publication,
subsequent edits, and local or remote reverts, including partial reverts. Restore
origin access and retry. No unverified marker becomes a merge base, and the sync
record stays unchanged on this refusal. Files without publication changes still
merge from the recorded base with a warning; equal published copies remain safe.

Remote plain-file checks and collisions with the generated sync-record path run
before publication recognition. Modify/delete and concurrent-change checks use
the selected merge base. Running them against the older recorded base first
would reject edits already reconciled in a publication. A structurally valid
publication may therefore require history completion before a later content
refusal; the announced permanent history change is not rolled back.

Temporary review-ref cleanup reports a sanitized warning on failure without
masking the operation's result. Such a failure can leave that temporary ref in
the workspace; branch refs remain untouched.

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
