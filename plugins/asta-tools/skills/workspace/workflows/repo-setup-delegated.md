# Workflow: repo setup for someone else

Follow this from [repo setup](repo-setup.md) when the account
`gh api user -q .login` reports isn't the person who asked for the workspace
(the requester), for example an agent creating the repo under its own GitHub
account. Build the private workspace and open its setup PR even if you can't
confirm the requester is an admin. For failures outside the permission step,
stop and tell the requester what failed, including GitHub's error when
available. Compare GitHub logins case-insensitively throughout.

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
4. Before creating anything, read `gh api users/<login> -q .login` and require
   it to match the verified requester login. Stop if GitHub can't confirm the
   account. This lookup checks the account still exists.

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

1. [Read the requester's access](#read-access-and-choose-one-line). If the
   permission read failed or was unexpected, recheck that the exact target repo
   is still accessible and private as in section 3. Stop if that recheck fails.
   Skip the grant if admin is confirmed, access is unconfirmed, or an
   invitation is pending.
2. For verified `none`, `read`, or `write` with no known pending invitation, try
   the grant once:
   `gh api --include -X PUT repos/<owner>/<name>/collaborators/<login> -f permission=admin`.
   - `201`: record the pending invitation alongside the permission you read.
   - A tool refusal or an HTTP rejection such as `403` or `422`: keep the
     permission you read and record that the grant was refused.
   - `204` or an unclear result: repeat only the read-only access check and use
     its result for the handoff.

Continue to section 5 after any grant outcome. Leave further grant attempts
for an explicit request from the requester.

## 5. Return to repo setup

Resume [Apply](repo-setup.md#2-apply) inside step 1, after its repo creation:
if the repo has no branches (an existing empty repo), push the empty-tree root
commit to `main`; then merge the established default branch into the local
workspace, and continue at step 2.

With confirmed `admin`, use the normal step 4 handoff. Otherwise, once the
setup PR checks pass (or `make check` passes with Pages off), send only the
following lines.

- "Your private workspace is built in <PR link>." With `none` or unconfirmed
  access, add "You can open the PR once you have access." With confirmed
  `read` or `write` access and Pages on, include the private preview and any
  paper PDF link from step 4.
- One access line from [below](#read-access-and-choose-one-line).
- "After you've reviewed it, merge the PR or ask an authorized maintainer to
  merge it. Tell me once it has merged so I can finish the setup."

Leave the PR open for the requester's review. On a follow-up, check the setup
PR's state. If it has merged and setup is still pending, finish steps 5–7 of
[Apply](repo-setup.md#2-apply).

On an explicit request for admin access, recheck the requester identity, the
existing private organization repo, and its setup PR. Repeat the access and
grant steps in section 4 on that repo and resume from the existing PR.
If the requester also explicitly asks you to merge a PR they've reviewed,
follow Apply step 4's authorization and checks. If the PR stays open, give
its link, one access line, and the same request to report the merge. Include
the preview and paper PDF when available to the requester. If the PR has
merged, use the final reply in Apply step 7 for a setup you just finished,
or send one access line if setup was already complete.

### Read access and choose one line

Read `gh api repos/<owner>/<name>/collaborators/<login>/permission -q '{permission, role_name}'`
for the verified requester. Use `.permission` for the effective access (`admin`,
`write`, `read`, or `none`). [`role_name`](https://docs.github.com/en/rest/collaborators/collaborators#get-repository-permissions-for-a-user)
can describe a custom role. A failed or unexpected permission read leaves
access unconfirmed. Unless admin is confirmed, also read
`gh api --paginate repos/<owner>/<name>/invitations` and look for a pending
invitation whose `invitee.login` matches the verified requester. A failed list
leaves invitation status unknown. A `201` grant in the current step also
confirms an invitation.

Use the first matching line.

- `admin`: "You're its admin."
- Pending invitation: "Accept your repository invitation at
  <https://github.com/<owner>/<name>/invitations>." If access is `none`, start
  the line with "You don't have repo access yet."
- `none`: "You don't have repo access yet. Ask an organization admin to grant
  you access to <owner>/<name>."
- `read` or `write`: "You have <read or write> access. Ask an organization
  admin if you need admin access."
- Unconfirmed: "I couldn't verify your repo access. Ask an organization admin
  to check your access to <owner>/<name>."
