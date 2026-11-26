# 11: Online Shop daily totals are not checked for plausibility

Status: needs-triage
Blocked by: None
Source: retail-ops-agent Issue 02 (Review Session Non-critical Finding), triaged in Issue 07

**Where it is now (on `main` at `cfaa54f`):** `src/retail_ops_agent/upload_formats.py:425` (per-line check), `:457-467` (`_daily_totals`)

Online Shop Order Lines are checked against `MAX_PLAUSIBLE_DAILY_UNITS` one line at a time. The paid lines are then added up per SKU and the total is never checked, so many plausible lines can add up to an impossible daily sale without a Defect.

- [ ] Check each SKU's daily total too, with a test.
