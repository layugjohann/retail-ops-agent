# 30: The `demand_surge` cause patterns accept wrong causes

Status: needs-triage
Blocked by: None
Source: retail-ops-agent Issue 12 (Review Session Non-critical Finding), triaged in Issue 07

**Where it is now (on `main` at `cfaa54f`):** `src/retail_ops_agent/evals/action_graders.py:35-46`, used at `:97-99`

`CAUSE_PATTERNS` for `demand_surge` matches phrases like "far more than", "more than usual" and "above the usual". A wrong cause worded that way ("a price cut made it sell far more than usual") passes `analyst_cause`.

- [ ] Tighten the patterns, and add negative test cases for the other causes.
