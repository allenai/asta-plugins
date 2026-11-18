# Workflow: repo setup for someone else

Follow this from [repo setup](repo-setup.md) when the account
`gh api user -q .login` reports isn't the person who asked for the workspace
(the requester), for example an agent creating the repo under its own GitHub
account. Build the private workspace and open its setup PR even if you can't
confirm the requester is an admin. For failures outside the permission step,
stop and tell the requester what failed. Compare GitHub logins
case-insensitively throughout.

## 1. Identify both accounts

1. Read the acting login with `gh api user -q .login`; stop if it cannot be
   identified.
2. Resolve the requester's GitHub login from authenticated request context or
   a trusted, verified identity mapping. A self-reported login or name match
   alone is insufficient: have the acting account's human or an org admin
   verify the requester-to-login link, and stop until it is verified. Looking
   up an account proves that it exists, not that it belongs to the requester.
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

Create the repo private with a README, so the default branch exists
(`gh repo create <owner>/<name> --private --add-readme`), or make an existing
empty repo private. Push nothing yet. Read
`gh api repos/<owner>/<name> -q '{full_name, private}'` and verify the exact
target and `private: true`; stop on a mismatch or failed read.

## 4. Check and try to grant admin access

1. Check the requester's effective permission, where `<login>` is their
   verified login:
   `gh api repos/<owner>/<name>/collaborators/<login>/permission -q '{permission, role_name}'`.
   Use `.permission` for the effective base access (`admin`, `write`, `read`,
   or `none`). [`role_name`](https://docs.github.com/en/rest/collaborators/collaborators#get-repository-permissions-for-a-user)
   can describe a custom role. If the result is `admin`, continue without a
   grant. If the read fails or the result is unexpected, record access as
   unconfirmed and continue without attempting a grant.
2. If `.permission` is `none`, `read`, or `write`, try the grant once:
   `gh api --include -X PUT repos/<owner>/<name>/collaborators/<login> -f permission=admin`.
   - `201`: record a pending invitation alongside the permission you read.
   - A tool refusal or a definite rejection from GitHub: keep the permission
     you read and record that the grant was refused.
   - `204` or an unclear result: repeat only the permission read. Use its
     result for the handoff. If that read fails, access is unconfirmed.

Continue to section 5 after any grant outcome. Leave further grant attempts
for an explicit request from the requester.

## 5. Return to repo setup

Resume [Apply](repo-setup.md#2-apply) inside step 1, after its repo creation:
if the repo has no branches (an existing empty repo), push the empty-tree root
commit to `main`; then merge the established default branch into the local
workspace, and continue at step 2.

With confirmed `admin`, use the normal step 4 handoff. Otherwise, once the
setup PR checks pass (or `make check` passes with Pages off), send “Your private
workspace is built and ready to review in <PR link>. An authorized maintainer
can review and merge it.” Include the private preview and any paper PDF link
from step 4 when Pages is on and the requester has confirmed `read` or `write`
access. Add one line about access:

- Pending invitation: “Accept your admin invitation at
  <https://github.com/<owner>/<name>/invitations>.” If access is `none`, start
  the line with “You don't have repo access yet.”
- `none`: “You don't have repo access yet. Reply to request admin access.”
- `read` or `write`: “You have <read or write> access. Reply if you need admin
  access.”
- Unconfirmed: “I couldn't verify your repo access. Reply if you need admin
  access.”

Leave the PR open for review. Access and merge approvals are independent.
Finish steps 5–7 of [Apply](repo-setup.md#2-apply) after the setup PR is merged.

On an explicit request for admin access, recheck the requester identity, the
existing private organization repo, and its setup PR. Use section 4 on that
repo, pointing to any known pending invitation instead of sending another.
Say “You're its admin” only after a permission read confirms `admin`. If a
grant is still blocked, say what you verified and direct the requester to an
organization admin who can grant access. If the same reply explicitly
requests a merge, follow Apply step 4's authorization and checks. Otherwise,
or if the merge is refused, point to the PR for an authorized maintainer to
merge.
