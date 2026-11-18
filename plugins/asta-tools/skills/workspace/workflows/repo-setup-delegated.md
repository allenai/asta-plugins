# Workflow: repo setup for someone else

Follow this from [repo setup](repo-setup.md) when the account
`gh api user -q .login` reports isn't the person who asked for the workspace
(the requester), for example an agent creating the repo under its own GitHub
account. Setup makes the requester the repo's admin, but a refused admin grant
never stops it: setup finishes without their access, and the final reply says
in one line how they get it. Otherwise, when a step fails or GitHub reports
something unexpected, stop and tell the requester what GitHub said. Compare
GitHub logins case-insensitively throughout.

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

## 4. Make the requester admin

1. Check the requester's effective permission, where `<login>` is their
   verified login:
   `gh api repos/<owner>/<name>/collaborators/<login>/permission -q '{permission, role_name}'`.
   For a user with no access to a private organization repo, GitHub returns
   HTTP 200 with `"permission": "none"` and an empty `role_name`; every fresh
   repo starts here.
   - `admin`: go to section 5 without changing access, including when admin
     access comes through a team or organization role.
   - `none`, `read` or `write`: go to step 2.
   - Anything else, or a failed read (a `404` means the login isn't a GitHub
     user), stops setup for diagnosis.
2. Try the grant once:
   `gh api --include -X PUT repos/<owner>/<name>/collaborators/<login> -f permission=admin`.
   - `204`: rerun the permission check in step 1; it passes only on
     `.permission == "admin"` (the
     [permission API](https://docs.github.com/en/rest/collaborators/collaborators#get-repository-permissions-for-a-user)
     defines this as base access, while `role_name` also describes custom
     roles).
   - Anything else leaves the requester **without access**, and setup goes on
     to section 5 regardless: your harness or tools refuse to run the grant
     (for example, a permission mode that blocks access grants the requester
     didn't ask for), GitHub answers `201` (an invitation), any other status,
     or the recheck after a `204` returns something other than `admin` or
     fails. Don't retry the grant, run it another way or ask about it now;
     section 5 tells the requester how to get access.

## 5. Return to repo setup

Resume [Apply](repo-setup.md#2-apply) inside step 1, after its repo creation:
if the repo has no branches (an existing empty repo), push the empty-tree root
commit to `main`; then merge the established default branch into the local
workspace, and continue at step 2. In step 7, also tell the requester that
they are the repo's admin, but only once the permission check returned
`admin`.

When the requester is without access, they can't open the private preview or
merge, so finish setup for them:

- In step 4, merge the setup PR yourself once its checks pass, without sending
  step 4's message, and continue at step 5. If your merge is refused too, skip
  steps 5 and 6 and send only the last line below in place of step 7.
- In step 7, add in place of "You're its admin." the one line that fits:
  - After a `201`: "You don't have access yet: accept your invitation at
    <https://github.com/<owner>/<name>/invitations>."
  - Otherwise: "You don't have access yet: reply "make me its admin" and I'll
    add you."
  - If your merge was refused: "It's built but not published, and you don't
    have access yet: reply "add me and publish it" and I'll make you its admin
    and publish it."

When they reply asking for access, run section 4 from step 1, then resume
anything left unpublished at step 4's merge, and reply "You're its admin."
(with step 7's message if the site was just published). That reply is the
request a permission mode needed, so the grant isn't refused for want of it.
