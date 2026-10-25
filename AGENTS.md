# AGENTS.md

## KISS principle

Keep it simple. Prefer the most straightforward solution that works. Avoid unnecessary abstractions, premature optimization, and clever tricks. If there are two ways to do something, pick the simpler one.

## Git

Do not perform any write operations on git. Never commit, stage, merge, rebase, or push. Read-only commands (status, log, diff) are fine. The user handles all commits themselves.

## Comments

Do not add excessive comments. Code should speak for itself. Only add a comment to explain **why** something was done — never to explain **what** is being done.
