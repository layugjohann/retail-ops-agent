# 27: Some Tier 1 Actions can't be undone, but Tier 1 is defined as reversible

Status: needs-triage
Blocked by: None
Source: retail-ops-agent Issue 11 (Review Session Non-critical Finding), triaged in Issue 07

**Where it is now (on `main` at `cfaa54f`):** `src/retail_ops_agent/audit_log.py:46-47`, `:63-67`; `src/retail_ops_agent/ops_day.py:419-426`

`REPLACE_REORDER` and `WITHDRAW_REORDER` are Tier 1 but `NOT_UNDOABLE`. `GLOSSARY.md` (Action Tier) and ADR 0002 say Tier 1 is internal and reversible; the exception is explained only in a code comment.

- [ ] Make the undo reverse them, or record the exception in ADR 0002 and the glossary.
