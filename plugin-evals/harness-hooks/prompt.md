---
max_turns: 14
allowed_tools: [Read, Glob, Grep, Write, Edit, Skill, AskUserQuestion, "Bash(python3 *)"]
tags: [harness]
---

My PreToolUse hooks in this agent do not seem to do anything, and one of them
is supposed to block Bash. What is wrong with them, and what should the
callbacks look like? Explain first; I have not decided whether to change
anything.
