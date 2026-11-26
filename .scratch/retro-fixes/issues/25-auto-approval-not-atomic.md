# 25: An ERP refusal during auto-approval leaves the Ops Day half done

Status: needs-triage
Blocked by: None
Source: retail-ops-agent Issue 10 (Review Session Non-critical Finding), triaged in Issue 07

**Where it is now (on `main` at `cfaa54f`):** `src/retail_ops_agent/ops_day.py:282-304`, `_place_reorder` at `:459`

The Reorder is queued, and any earlier pending Reorder already replaced, before `_place_reorder` calls the ERP. If the ERP refuses, the exception stops the Ops Day, the item stays `pending`, and the Anomaly and Investigation are already recorded, so a rerun does not revisit them.

- [ ] Place first and queue after, or catch the refusal and record it, with a test using a refusing ERP.
