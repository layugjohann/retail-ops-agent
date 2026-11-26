# 40: The trigger returns no JSON error for unexpected exceptions

Status: needs-triage
Blocked by: None
Source: retail-ops-agent Issue 22 (Review Session Non-critical Finding), triaged in Issue 07

**Where it is now (on `main` at `cfaa54f`):** `src/retail_ops_agent/trigger.py:212-222` (`Handler._run`)

`Handler._run` catches only `NoDaysLeft` and `AgentRunError`. Any other error closes the connection without a JSON reply naming the problem, so n8n sees a dropped connection instead of a 500.

- [ ] Catch the rest and return a 500 with the error, with a test.
