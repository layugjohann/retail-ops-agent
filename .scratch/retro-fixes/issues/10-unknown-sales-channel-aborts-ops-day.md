# 10: An Upload for an unknown Sales Channel aborts the Ops Day

Status: needs-triage
Blocked by: None
Source: retail-ops-agent Issue 02 (Review Session Non-critical Finding), triaged in Issue 07

**Where it is now (on `main` at `cfaa54f`):** `src/retail_ops_agent/ops_day.py:222`, and `:888` in `_settle_upload`

`run_ops_day` indexes `channel_kinds[upload.sales_channel]` directly. An Upload in the Data Source for a Sales Channel the ERP doesn't know raises `KeyError` and stops the whole Ops Day, instead of the Upload being Quarantined with a Defect naming the unknown Sales Channel.

- [ ] Quarantine such an Upload with a clear Defect, and add a test.
