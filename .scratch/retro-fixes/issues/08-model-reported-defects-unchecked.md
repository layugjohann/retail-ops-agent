# 08: Model-reported Defects are not checked against the Upload

Status: needs-triage
Blocked by: None
Source: retail-ops-agent Issues 01, 16 (Review Session Non-critical Finding), triaged in Issue 07

**Where it is now (on `main` at `cfaa54f`):** `src/retail_ops_agent/intake.py:129-136`

`run_intake` adds every Defect the Intake model reports to the deterministic ones without confirming it. The only filter drops Defects whose `column` is the free-text column. So a model that invents a Defect, or obeys a Prompt Injection and reports a Defect with no column or on another column, Quarantines an otherwise clean Upload. That goes against the spec's "a clean Upload is never Quarantined".

- [ ] Accept a model-reported Defect only if a deterministic check confirms it, or use the model only to write the Uploader message.
