# 15: A released header-Defect Upload shows as accepted with no rows

Status: needs-triage
Blocked by: None
Source: retail-ops-agent Issue 04 (Review Session Non-critical Finding), triaged in Issue 07

**Where it is now (on `main` at `cfaa54f`):** `src/retail_ops_agent/ops_day.py:886-897`; `src/retail_ops_agent/views.py:26-41` (`UploadOutcome`)

Releasing a Quarantine for a missing or swapped column sets the Upload to `accepted` while loading no rows (ADR 0008 says so). The Upload status view has no rows-loaded field, so a BI analyst can't tell "accepted, nothing loaded" from a normal accept.

- [ ] Show rows loaded (or a distinct note) in the Upload status view.
