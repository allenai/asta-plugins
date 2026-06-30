---
name: brainstorm
description: Converse with the user to identify the next most productive units of work for the current project, and record them in project.md under Pending Work. Use when the user wants to plan what to work on next, or when there is no project.md yet.
allowed-tools: Read(*) Write(project.md) Edit(project.md)
---

# Brainstorm

Conversational skill. Examines the project state and helps the user decide what to do next. The only artifact this skill writes is `project.md` (creating it if missing, otherwise updating its Pending Work section).

## Inputs

- `project.md` (optional). If missing, this skill bootstraps it from the conversation.
- `work/index.yaml` (optional). Lists previously-recorded work items.
- `work/<slug>/README.md` (optional). The current state of completed and pending work.

## Outputs

- `project.md` with structure:
  ```markdown
  # Goal
  <multi-paragraph statement of the overall research/engineering goal>

  # Background
  <context, constraints, prior work, data sources>

  # Completed Work
  - [<slug>](work/<slug>/README.md) — <one-line summary>

  # Pending Work
  - [<slug>](work/<slug>/README.md) (status: <pending-plan|ready|...>) — <one-line summary>
  ```

## Procedure

1. **Read state.** Open `project.md` if it exists, plus `work/index.yaml` and any READMEs it references. If `project.md` is missing, ask the user about the goal and background and draft a first version — do **not** invent goals or background.

2. **Converse.** Discuss what would be most productive to do next given the goal, what is already complete, and what is pending. Ask clarifying questions when scope is ambiguous. Surface tradeoffs rather than picking unilaterally.

3. **Propose work items.** Each new unit of work should be small enough that a single planning pass can describe it concretely. For each:
   - Slug (kebab-case, unique under `work/`)
   - One-line summary
   - Why it's the right next step

4. **Confirm before writing.** Show the proposed Pending Work changes to the user and wait for explicit approval.

5. **Write artifacts.** For each approved item:
   - Append a line to the Pending Work section of `project.md`:
     `- [<slug>](work/<slug>/README.md) (status: pending-plan) — <one-line summary>`
   - Create `work/<slug>/README.md` with frontmatter and a Goal section only — leave Instructions, Results, Assessment empty for later skills to fill in:
     ```markdown
     ---
     slug: <slug>
     status: pending-plan
     ---

     # Goal
     <multi-paragraph goal description>

     # Instructions

     # Results

     # Assessment
     ```

## Out of scope

- Writing detailed plans (that is **plan-work**).
- Executing work (that is **do-work**).
- Reviewing or assessing outcomes (that is **review-plan** and **review-work**).
- Committing or indexing artifacts (that is **save-work**).
