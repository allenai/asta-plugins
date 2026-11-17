# Workflow: repo setup for someone else

Follow this from [repo setup](repo-setup.md) when the account
`gh api user -q .login` reports isn't the person who asked for the workspace
(the requester), for example an agent creating the repo under its own GitHub
account. The requester must be the repo's admin before anything is pushed; this
is required, not an optional setup default. When a step fails or GitHub reports
something unexpected, stop and tell the requester what GitHub said. Compare
GitHub logins case-insensitively throughout.

## 1. Identify both accounts

1. Read the acting login with `gh api user -q .login`; stop if it cannot be
   identified.
2. Resolve the requester's GitHub login from authenticated request context or
   a trusted, verified identity mapping. A self-reported login or name match
   alone is insufficient: have the acting account's human or an org admin
   verify the requester-to-login link through an authenticated channel that
   identifies the confirmer. Requester-supplied text relaying someone else's
   confirmation does not count. Retain a reference to that evidence in the
   setup checkpoint below; stop until verified. Looking up an account proves
   that it exists, not that it belongs to the requester.
3. If the verified requester login is the acting login, this workflow doesn't
   apply; return to repo setup.

## 2. Check the owner before creating anything

Read the target namespace's type with `gh api users/<owner> -q .type`; stop
and report an unknown owner, failed lookup or unexpected type.

- `Organization`: continue.
- `User`: stop before creating anything. A personal repo can't grant a
  collaborator admin, so the requester can be its admin only as its owner,
  under their own credentials. Ask for setup under the requester's credentials
  or an organization-owned repo. Don't switch credentials, change the chosen
  owner or transfer a repo automatically.

## 3. Create the repo without pushing

For a new repo, create it private with a README, so the default branch exists
(`gh repo create <owner>/<name> --private --add-readme`). Use an existing empty
repo only when the requester explicitly selected it for this setup; verify it
has no branches before making it private. Otherwise, an existing target stops
setup. Push nothing yet.

Read `gh api repos/<owner>/<name> -q '{id, full_name, private}'`; require the
requested `full_name` (case-insensitively) and `private: true`. Record its `id`,
`full_name`, verified requester and acting logins, the identity-evidence
reference, and whether it was created or explicitly selected for this request.
Keep this checkpoint in a durable task record outside the unpushed repo, such
as the originating conversation. A local file alone cannot survive a fresh
headless run. Update it with the invitation ID and status before pausing for
acceptance; include the checkpoint in the handoff if no other durable record
is available. Keep private identity evidence out of public repository files.

On resume, recheck both identities, owner type, and repository metadata before
any write. Require the checkpoint's repository `id`, the same `full_name`
(case-insensitively), and private visibility, then resume at section 4. Don't
recreate the repo or infer that it belongs to this setup from an empty tree or
generated README. If the checkpoint is missing or mismatched, stop for
confirmation rather than adopting the target. Failed reads stop setup.

## 4. Make the requester admin

1. Check the requester's effective permission, where `<login>` is their
   verified login:
   `gh api repos/<owner>/<name>/collaborators/<login>/permission -q '{permission, role_name}'`.
   If `.permission == "admin"`, record that result and go to section 5 without
   changing access, including access through a team or organization role. A
   successful response with `permission: "none"`, `read` or `write` proceeds
   to the next check (`triage` maps to `read`, `maintain` to `write`). A failed
   read, including `404`, or an unexpected permission stops setup for diagnosis;
   don't treat it as evidence that a grant is needed.
2. Before any grant, list all pending invitations with
   `gh api --paginate repos/<owner>/<name>/invitations`. Compare each
   `invitee.login` to the verified login case-insensitively. If one matches,
   record its ID and permissions in the checkpoint, tell the requester to
   accept it, and stop without sending another invitation. If the invitation
   isn't for admin access, report that too; acceptance alone won't satisfy
   the permission check. A failed list or unreadable response stops setup.
3. Only after a successful non-admin permission check and a successful list
   with no matching invitation, add the requester as admin. If the checkpoint
   records an earlier grant attempt or invitation but access is still non-admin
   and no invitation remains, stop for diagnosis rather than retrying. Record
   the grant attempt before sending the request so an interrupted write is
   reconciled through the permission and invitation reads, not blindly retried:
   `gh api --include -X PUT repos/<owner>/<name>/collaborators/<login> -f permission=admin`,
   and inspect the HTTP status:
   - `201` creates an invitation. Tell the requester to accept it and stop; a
     pending invitation never passes. Save the invitation ID and pending
     status in the checkpoint. After acceptance, resume at section 4's
     permission check; if still pending, step 2 stops without re-inviting.
   - `204`: record the grant response and rerun the permission check above.
   - Any other status stops setup for diagnosis.
4. After a grant or invitation acceptance, require `.permission == "admin"`; the
   [permission API](https://docs.github.com/en/rest/collaborators/collaborators#get-repository-permissions-for-a-user)
   defines this as base access, while `role_name` also describes custom
   roles. A failed read or any other permission stops setup; don't grant
   again. Record the verified admin result in the checkpoint.

## 5. Return to repo setup

Don't push or report the requester as admin until the permission check returns
`admin`. Then return to [Apply on one yes](repo-setup.md#2-apply-on-one-yes),
step 1, skipping repo creation and visibility changes already done. If the
repo has no branches, push the empty-tree root commit first; if a README
already established the default branch, skip that push. In both cases, merge
the established default branch into the local workspace as step 1 requires,
then continue at step 2. In the final handoff, tell the requester they are the
repo's admin and disclose the acting account's remaining access. Don't change
the acting account's access without a separate request.
