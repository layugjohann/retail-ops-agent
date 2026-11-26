# 14: No test checks every planted column rename is a known alias

Status: needs-triage
Blocked by: None
Source: retail-ops-agent Issue 03 (Review Session Non-critical Finding), triaged in Issue 07

**Where it is now (on `main` at `cfaa54f`):** `src/retail_ops_agent/generator/defects.py:67-82` (`_RENAMES`), `src/retail_ops_agent/safe_fixes.py:20-35` (`COLUMN_ALIASES`)

The generator's renames and the Safe Fix aliases are two hand-kept lists. They agree today, but the only test is parametrised over whichever variants the RNG picks, so a new rename with no alias would go unnoticed until an eval plants it.

- [ ] A test that every entry in `_RENAMES` maps to its column through `COLUMN_ALIASES`.
