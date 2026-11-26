# 19: A mistyped Sales Channel in a Golden Scenario is silently ignored

Status: needs-triage
Blocked by: None
Source: retail-ops-agent Issue 07 (Review Session Non-critical Finding), triaged in Issue 07

**Where it is now (on `main` at `cfaa54f`):** `src/retail_ops_agent/evals/scenarios.py:171-226`; `src/retail_ops_agent/sandbox.py:160-162`

`Scenario` checks `sales_channels` only for internal consistency, never against the catalog, and `Sandbox` drops unknown codes. A typo shows up only later as "never processed" grader findings.

- [ ] Reject unknown Sales Channel codes when the Scenario is loaded, naming the code.
