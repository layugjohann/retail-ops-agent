# 32: Anomalies that survive a Data Problem are investigated with stale figures

Status: needs-triage
Blocked by: None
Source: retail-ops-agent Issue 14 (Review Session Non-critical Finding), triaged in Issue 07

**Where it is now (on `main` at `cfaa54f`):** `src/retail_ops_agent/ops_day.py:246-269`

After a Data Problem sends Uploads back, `still_showing` filters the first detection's Anomaly objects by id. Those that still show are investigated with their first statistics, which may have changed once the Uploads left the BI data.

- [ ] Use the re-detected Anomalies' details, with a test.
