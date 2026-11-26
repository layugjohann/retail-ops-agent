# 35: Hours Saved counts a Safe-Fixed Upload once per Defect

Status: needs-triage
Blocked by: None
Source: retail-ops-agent Issue 17 (Review Session Non-critical Finding), triaged in Issue 07

**Where it is now (on `main` at `cfaa54f`):** `src/retail_ops_agent/ops_day.py:237`; `src/retail_ops_agent/hours_saved.py:123-125`; `src/retail_ops_agent/baseline.json:10`

Each Safe-Fixed Defect gets its own Audit Log entry and each entry is counted, so an Upload with several Safe-Fixable Defects counts the 10-minute hand fix several times. `baseline.json` describes the frequency per Upload and `docs/discovery/baseline.md` never says the count is per Defect.

- [ ] Count per Upload, or state per-Defect counting in `baseline.md`.
