# 16: A late Upload for a day with nothing processed is never picked up

Status: needs-triage
Blocked by: None
Source: retail-ops-agent Issue 05 (Review Session Non-critical Finding), triaged in Issue 07

**Where it is now (on `main` at `cfaa54f`):** `src/retail_ops_agent/ops_day.py:197`; `src/retail_ops_agent/bi_store.py:192-194` (`upload_days`)

`run_ops_day` re-scans only earlier days that already have a processed Upload. A late Upload for an earlier day with nothing processed yet is never processed by a later Ops Day, and an Upload for a day after `day` is ignored when an earlier day runs.

- [ ] Decide which days an Ops Day collects pending Uploads from, and test the late-Upload case.
