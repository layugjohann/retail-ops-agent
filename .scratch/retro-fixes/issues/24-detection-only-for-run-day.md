# 24: A resubmission for an earlier day never triggers detection for that day

Status: needs-triage
Blocked by: None
Source: retail-ops-agent Issue 09 (Review Session Non-critical Finding), triaged in Issue 07

**Where it is now (on `main` at `cfaa54f`):** `src/retail_ops_agent/ops_day.py:247` (`self._detect(day)`)

Detection runs only for the day passed to `run_ops_day`. Resubmissions for earlier days are loaded and `_recheck` can clear Anomalies that no longer hold, but an Anomaly a resubmission newly reveals on an earlier day is never detected.

- [ ] Decide whether a resubmitted earlier day is re-detected; document it (ADR) or implement it.
