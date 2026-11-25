# 07: Triage the remaining Review Findings

Status: ready-for-agent
Blocked by: 01

**What to build:** Sweep every Non-critical Finding in the `## Comments` of
`.scratch/retail-ops-agent/issues/*.md` (about 100, across 22 Issues) and decide what happens to each.
Issue 01 already covers the confirmed bugs, so skip those.

For each Finding, check `main` and put it in exactly one of these groups:
- **Gone**: already fixed, or the code it names no longer exists.
- **Bug or gap still present**: write a new Issue file in `.scratch/retro-fixes/issues/` (next free number,
  `Status: needs-triage`), naming the source Issue and the file and line where the bug is now.
- **Style or naming only**: list it in this Issue's comment. Don't file it.

- [ ] Every Finding in Issues 01 to 25 is in one of the three groups. The comment on this Issue lists each Finding
      under its group, with the source Issue number.
- [ ] No code changes in this Issue: it only files Issues.
