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
empty repo private. Push nothing yet. When resuming this same setup, reuse the
repo already created for this request, including its generated README; don't
recreate it or adopt an unrelated nonempty repo. Read
`gh api repos/<owner>/<name> -q '{full_name, private}'` and verify the exact
target and `private: true`; stop on a mismatch or failed read.

## 4. Make the requester admin

1. Check the requester's effective permission, where `<login>` is their
   verified login:
   `gh api repos/<owner>/<name>/collaborators/<login>/permission -q '{permission, role_name}'`.
   If `.permission == "admin"`, go to section 5 without changing access,
   including when admin access comes through a team or organization role. A
   failed read stops setup for diagnosis; don't treat it as evidence that a
   grant is needed.
2. Only if the check succeeds with a non-admin permission, add the requester
   as admin:
   `gh api --include -X PUT repos/<owner>/<name>/collaborators/<login> -f permission=admin`,
   and inspect the HTTP status:
   - `201` creates an invitation. Tell the requester to accept it and stop; a
     pending invitation never passes. After acceptance, resume at the
     permission check above without recreating the repo or sending another
     invitation.
   - `204`: rerun the permission check above.
   - Any other status stops setup for diagnosis.
3. After a grant, require `.permission == "admin"`; the
   [permission API](https://docs.github.com/en/rest/collaborators/collaborators#get-repository-permissions-for-a-user)
   defines this as base access, while `role_name` also describes custom
   roles. A failed read or any other permission stops setup; don't grant
   again.

## 5. Return to repo setup

Don't push or report the requester as admin until the permission check returns
`admin`. Then continue [repo setup](repo-setup.md) at step 1's root-commit push,
skipping the creation already done. In its final step, also tell the requester
that they are the repo's admin.
