# Spec: retro fixes

Status: ready-for-agent

Fixes from the 2026-11-25 retrospective over the 26 retail-ops-agent Issues (61 Sandcastle sessions, 20 Gate logs,
every Issue's `## Comments`). Terms have the meanings in `GLOSSARY.md`.

## Problem Statement

- Review Sessions logged about 100 Non-critical Findings. None were acted on, and some are real bugs still on `main`.
- The test suite grew from 22 s (Issue 01) to about 6.5 min (Issue 17). Implementers ran it 5 to 20 times per Issue.
- No CI and no git hook: work done outside a Sandcastle Run never passes the Gate.
- Some coding standards are mechanical (banned calls, banned imports, dead code) but only a Review Session checks them.
- `ThrottledModel` silently waits out any `retry_after`. A 2h24m Groq wait looked like a hang, two eval runs were lost,
  and a timeout (`d67a5b9`) was added for the wrong cause.
- The GLOSSARY rule was flagged in 10 of 22 reviews and `GLOSSARY.md` hasn't changed since Issue 18.

## Solution

One Issue per fix, in `issues/`. The two fixes to the Run itself (telling the Implementer about the sandbox's limits,
and turning Non-critical Findings into Issues) live in the sandcastle-pro repo's own tracker, Issues 18 and 19.

## Out of scope

- A linter for GLOSSARY _Avoid_ words. The glossary lists 140 of them, and many are ordinary code words (`run` alone
  matches 75 identifiers, including `run_ops_day` and `AgentRunError`), so the check would be mostly noise.
