---
name: run
description: Router skill that advances the project autonomously. Examines project.md Pending Work, dispatches to do-work for ready items or plan-work otherwise, and loops until no actionable work remains. Use when the user says "keep going", "work on the project", "run the next step".
allowed-tools: Read(project.md) Read(work/**) Read(/tmp/**) Write(/tmp/**) Edit(/tmp/**) Skill(asta-assistant:do-work) Skill(asta-assistant:plan-work) Skill(asta-assistant:brainstorm) Skill(asta-assistant:save-work)
---

# Run

Router. Drives the project forward by repeatedly picking the next action from `project.md` and handing off to the appropriate skill.

## Preconditions

- `project.md` exists. If not, hand off to **brainstorm** to draft one.

## Procedure

1. **Read state.** Open `project.md`. Parse the Pending Work section into a list of items with `slug` and `status`.

2. **Pick the next action.**
   - If any items have `status: done`, hand off to **save-work** to persist them before doing anything else. Batching in one call is fine.
   - Else if any item has `status: ready`, pick the first one and hand off to **do-work** with that slug.
   - Else if any item has `status: pending-plan`, pick the first one and hand off to **plan-work** with that slug.
   - Else if any item has `status: needs-input`, stop and ask the user to resolve it.
   - Else (no actionable items) stop and hand off to **brainstorm**.

3. **After the handoff returns**, re-read `project.md` and loop back to step 2. Stop when:
   - There is nothing actionable, **or**
   - The user has interrupted, **or**
   - The same item failed twice in a row (avoid tight failure loops — surface to the user).

## Status conventions

| Status | Meaning | Next skill |
|---|---|---|
| `pending-plan` | Goal known, no detailed plan yet | **plan-work** |
| `pending-review` | Plan written, awaiting **review-plan** | (handled internally by **plan-work**) |
| `ready` | Plan approved, ready to execute | **do-work** |
| `in-progress` | **do-work** is running | (skip; do not re-enter) |
| `done` | Work and review complete | **save-work** |
| `needs-input` | Blocked, requires user input | (stop and ask) |

## Out of scope

This skill never modifies `project.md` or work READMEs directly. It only reads state and dispatches.
