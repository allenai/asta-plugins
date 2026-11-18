# Workflow: repo setup for someone else

Follow this from [repo setup](repo-setup.md) when the account
`gh api user -q .login` reports isn't the person who asked for the workspace
(the requester), for example an agent creating the repo under its own GitHub
account. The admin grant in section 4 never stops setup. When any other
step fails or GitHub reports something unexpected, stop and tell the requester
what GitHub said. Compare GitHub logins case-insensitively throughout.

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

## 4. Try once to make the requester admin

1. Read the requester's effective permission, where `<login>` is their
   verified login:
   `gh api repos/<owner>/<name>/collaborators/<login>/permission -q .permission`.
   If it is `admin` (directly, through a team or an organization role), go to
   section 5.
2. Otherwise, try the grant once:
   `gh api --include -X PUT repos/<owner>/<name>/collaborators/<login> -f permission=admin`.
   After a `204`, read the permission again. Don't retry or work around a
   refusal, whether from GitHub or from your own tools: those can refuse a
   permission grant the requester didn't ask for.

Whatever the outcome, continue to section 5, and pick the access line:

- Confirmed `admin`: "You're its admin."
- A `201` (an invitation): "Accept your invitation at
  <https://github.com/<owner>/<name>/invitations> to open it."
- Anything else: "You don't have admin access yet: reply 'make me its
  admin' and I'll grant it."

That reply is the requester's own request for the grant, so repeat this
section once on it and reply with the new access line. They then review and
merge the setup PR as in any start.

## 5. Return to repo setup

Resume [Apply](repo-setup.md#2-apply) inside step 1, after its repo creation:
if the repo has no branches (an existing empty repo), push the empty-tree root
commit to `main`; then merge the established default branch into the local
workspace, and continue at step 2. In step 4, add the access line from
section 4 to its message.
