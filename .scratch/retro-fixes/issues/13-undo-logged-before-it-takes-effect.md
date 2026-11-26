# 13: An undo is logged before it takes effect

Status: needs-triage
Blocked by: None
Source: retail-ops-agent Issue 03 (Review Session Non-critical Finding), triaged in Issue 07

**Where it is now (on `main` at `cfaa54f`):** `src/retail_ops_agent/ops_day.py:579-599` (`_append_undo`)

`_append_undo` appends the undo entry to the Audit Log first, then calls `_settle_upload`, with no transaction. If settling fails (for example `_processed_upload` raising `KeyError` at `ops_day.py:907` because the Upload is gone from the Data Source), the Audit Log records an undo that never happened.

- [ ] Settle first and log after, or roll the entry back on failure, with a test.
