# 23: The planner is not told when an alert is withdrawn

Status: needs-triage
Blocked by: None
Source: retail-ops-agent Issue 09 (Review Session Non-critical Finding), triaged in Issue 07

**Where it is now (on `main` at `cfaa54f`):** `src/retail_ops_agent/ops_day.py:522-526` and `_append_undo` at `:565-597`

Posting an alert sends a Notification (`ops_day.py:506`), but undoing it (by hand or through a Supersede in `_recheck`) only writes the Audit Log entry. The recipient still believes the alert stands, so the undo recipe's wording overstates what happens.

- [ ] Send a withdrawal Notification to the alert's recipient, with a test.
