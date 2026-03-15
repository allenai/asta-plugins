---
name: research step
description: Do one step of autonomous research, based on the current research state in the current working directory. Use when asked to "run AstaBot" "do an AstaBot step", "AstaBot, or "do a research step".
allowed-tools: Bash, Read, Write
---

# Research Loop

## Initialization

Look at the mission.md file in the current directory. This is the current research mission to perform reserach on.

If there is NOT a mission.md file, exit this skill with a message saying:
* "Please provide a mission.md file! See examples at https://tinyurl.com/example-missions"

Otherwise, continue.

## Setup

Look to see if there is a research_state.md file in the current directory.

If there is one, go to the next step.

If there is NOT one, then create it as follows: This file, research_state.md, is to be a LIVING RESEARCH document for keeping track of research progress for the research mission (mission.md), that you can use in collaboration with other researchers working with you. The idea is that both you and the other researchers can contribute to the document, use it for inspiration as next steps, and each update information in the documents as the research continues.

Now create a research_state.md file and write into it your own initial hypotheses and observations about the mission, to help get started. It is fine to leave sections blank until future research fills in the details. Where appropriate, include your rough confidence estimates (as a percentage) in the document. The document should help new researchers join the effort, and quickly learn about what we know and what we don't, and where in the research process the team is, and what tasks should be done next, so that they can easily see where to contribute. 

To help plan your research, you will later have tools you can use including:
 - literature search
 - end-to-end autonomous experimentation
 - asking questions to a LLM
 - other tasks

Now, here is a suggested structure for the LIVING RESEARCH document research_state.md.

1. Research Question & Scope
2. Operational Definitions
3. Related Work
4. Hypotheses (H1, H2, H3, ...)
5. Experimental Designs
6. Results Summary
7. Open Questions & Confusions

## Research

Finally, run a single iteration of the following research loop:

1. Read the research_state.md file to understand the current research mission and current state
2. Analyze what has been done and decide the next concrete TASK to perform
3. Summarize relevant background knowledge / context that is needed to understand TASK and perform it correctly. Create a file background_knowledge.txt and write that summary into it. If background_knowledge.txt already exists, overwrite it.
4. Select and invoke the most appropriate skill for that subtask. For example, to run an experiment, use the run-experiment skill (which invokes the Panda research tool).

When that task has been completed:

5. Make a backup copy of research_state.md to the "history/" folder:
   a. Look in the "history/" directory for backup copies of research_state.md, e.g., "reearch-bk1.md", "research-bk2.md". If the directory doesn't exist create it.
   b. Place a backup copy of research_state.md in the "history/" directory, called "research_state_bk<N>.md" where N is the next unused number (1 if this is the first backup).
6. UPDATE the main research_state.md with the results, so that the current state of research is up to date, including a correct summary of what has been done, what is still to do, and what has been learned. research_state.md should be ready then for the next iteration of the research.

## End

Exit with the message "Iteration complete"





