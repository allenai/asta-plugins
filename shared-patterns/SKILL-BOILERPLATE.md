<!--
SKILL-BOILERPLATE.md — a starting point for new Asta skills.

How to use:
1. Copy this file to `skills/<your-skill-name>/SKILL.md`.
2. Replace the [bracketed placeholders] with your skill's content.
3. The markdown prose below (everything after the frontmatter) is meant
   to kickstart skill development, not constrain it. Every section is
   optional — keep what's useful, delete what isn't, add what you need.
4. Delete this comment block before you ship.
-->

---
name: [Skill Name]
description: [When the skill should trigger. Include both what it does AND the user phrasings/contexts that should invoke it. Lean slightly pushy — skills tend to undertrigger.]
metadata:
  internal: true
allowed-tools:
  - Bash([specific commands the skill needs])
---

# [Skill Name]

[2–3 sentences: what the skill does, what agent or system it talks to, and the auth command if there is one. Link the upstream repo.]

**Voice and tone:** Follow [`shared-patterns/voice-and-tone.md`](../../shared-patterns/voice-and-tone.md) for all user-facing chat. Applies to every output the user reads.

## Installation

This skill requires the `asta` CLI. If it is missing or out of date, run the install block in [`shared-patterns/installation.md`](../../shared-patterns/installation.md) before invoking any `asta` command.

[If the skill needs extra setup beyond the CLI — auth, credentials, extra deps — describe it here. Otherwise leave this section as just the line above.]

## What this skill is good for

[2–3 bullet points]

## What this skills is NOT for

[2–3 bullet points]

## References

- Shared patterns:
  - `shared-patterns/voice-and-tone.md`
  - `shared-patterns/installation.md`