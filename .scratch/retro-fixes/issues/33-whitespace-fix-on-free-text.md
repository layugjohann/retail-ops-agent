# 33: The whitespace Safe Fix runs on free-text columns

Status: needs-triage
Blocked by: None
Source: retail-ops-agent Issue 16 (Review Session Non-critical Finding), triaged in Issue 07

**Where it is now (on `main` at `cfaa54f`):** `src/retail_ops_agent/safe_fixes.py:109-122`; comment at `src/retail_ops_agent/upload_formats.py:54-57`

The stray-whitespace pass covers every cell, free text included. A description or order note with spaces around it makes an otherwise clean Upload `safe_fixed`, with a Safe Fix on the free-text column, which contradicts the comment that free text is never validated.

- [ ] Skip free-text columns in the whitespace pass, or correct the comment.
