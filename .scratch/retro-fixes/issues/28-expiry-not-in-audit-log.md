# 28: Expiry leaves no Audit Log entry

Status: needs-triage
Blocked by: None
Source: retail-ops-agent Issue 11 (Review Session Non-critical Finding), triaged in Issue 07

**Where it is now (on `main` at `cfaa54f`):** `src/retail_ops_agent/ops_day.py:372-388` (`_expire`)

Expiring a Tier 2 Action is a policy decision, but `_expire` only changes the Approval Queue status. Replacement and withdrawal each write an Audit Log entry; expiry does not, so the Audit Log is not the full record of what happened to a Reorder.

- [ ] Write an Audit Log entry on expiry, with a test.
