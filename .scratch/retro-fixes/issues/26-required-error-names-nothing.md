# 26: `_required` raises an error that doesn't say what is missing

Status: needs-triage
Blocked by: None
Source: retail-ops-agent Issue 10 (Review Session Non-critical Finding), triaged in Issue 07

**Where it is now (on `main` at `cfaa54f`):** `src/retail_ops_agent/ops_day.py:1039-1042` (used at `:288`, `:303`, `:433`, `:568`)

`_required` raises `ValueError("missing value")` without naming the value, against the standard that errors name the problem.

- [ ] Take a name argument and include it in the message.
