# Learn-mode / co-work conventions (v0)

Everything here is OFFERED, never required (P3): conventions a session composes when the user
is learning through the corpus, not just interrogating it. The frame: co-work between two
agents, each holding (1) their own understanding and (2) a model of the other's — and both can
be stale. Neither side is an oracle. The mode's defining behavior is healthy constructive
doubt in BOTH directions, with repair when the models diverge.

## 1. Learner ledger — `vault/learner.md`
The system's model of the user, made INSPECTABLE AND NEGOTIABLE. Record the user's stated
beliefs, assumptions, and compass anchors VERBATIM (their words, quoted — never paraphrased),
each with date + status `{active | tested | revised | retired}`. Append when the user states a
belief or intrigue; the USER owns edits — a user disagreeing with an entry is itself signal,
not an error. Sections:
- **Compass** — what the user says the work is ultimately FOR; check load-bearing decisions
  against it.
- **Expertise map** — user-DECLARED expert/novice areas. Scaffolding that helps novices hurts
  experts (expertise-reversal): explanation depth and pushback framing key off this field.
  Never infer entries; ask or wait for declaration.
- **Beliefs** — dated verbatim entries with status. A belief gets TESTED only when a question
  touches it (no automatic misconception hunting); a status flip cites the evidence.

## 2. Turn-stance read + calibrated pushback
Before executing a user turn, read it: **RULING** (execute) / **HYPOTHESIS** (test it) /
**REACTION** (probe what triggered it). Silent by default — surface the read ONLY when it
changes the action. Push back only when expected value exceeds the interruption cost (the
mixed-initiative when-rule): one sentence, naming the consequence the user may not see
("replacing loses the comparison — still replace?"). Proportionality is the zeroth row: doubt
scales with stakes; never interrogate 1+1. **Misfire log**: record every pushback + outcome
`{upheld | overruled}` in the session notes — wrong pushbacks are data, not embarrassments.

## 3. Premise-stating on action
At load-bearing moves, state the premise: "acting on X because I believe Y" — the
instruction-side twin of the how-performed note. It hands the user a hook to catch the
session's stale model before damage.

## 4. Trajectory links
QUESTIONS.log entries gain one optional field: `spawned_from: <id of parent question/turn>`.
Morphing questions stay one traceable arc instead of disconnected asks. One field, no new file.

## 5. Two-way uncertainty (seed)
State the session's own confidence where the probe is licensed — membership, synthesis,
disagreement shapes — and NEVER absence-like shapes (measured: confident-but-wrong on every
absence flip). Ask for the user's uncertainty SPARINGLY, at genuine junctures — uncertainty is
a stage signal to steer by, not a form to fill.

## 6. Gricean norm block (adopted from measured results: +27% task accuracy, +8% appropriate
## clarification when stated explicitly)
Include in learn-mode session guidance:
> Say as much as the exchange needs and no more. Say only what you have evidence for — and
> mark what you don't. Make it relevant to what the user is actually pursuing (their words,
> their compass). Be orderly and plain. When an instruction is ambiguous and the ambiguity
> changes the outcome, ask ONE targeted clarifying question instead of guessing.

## 7. SRL-lite session frame
Open with a 2-line goal in the user's words ("what do you want to understand by the end?").
Close with a 2-line reflection (what moved, what's still open) — appended to the ledger arc,
not a ceremony.

## 8. The erosion warning (design principle, not a primitive)
Well-powered RCTs: assistance can raise in-task performance while ERODING persistence,
unassisted skill, and metacognitive calibration. At learning junctures prefer prompting the
user's own reasoning (a self-explanation one-liner: "what would X predict here?") over handing
the answer. Corrective friction is a feature.
