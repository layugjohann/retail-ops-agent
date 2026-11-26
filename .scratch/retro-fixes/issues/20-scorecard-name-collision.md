# 20: Two eval runs in the same second overwrite each other's output

Status: needs-triage
Blocked by: None
Source: retail-ops-agent Issue 07 (Review Session Non-critical Finding), triaged in Issue 07

**Where it is now (on `main` at `cfaa54f`):** `src/retail_ops_agent/evals/scorecard.py:114`; `src/retail_ops_agent/evals/runner.py:268`

The Scorecard is named `scorecard-%Y%m%dT%H%M%S.json` and the Upload directory `uploads-%Y%m%dT%H%M%S`. Two runs started in the same second into one output directory overwrite each other's results.

- [ ] Use a finer timestamp or a unique suffix, or refuse to overwrite.
