# 39: The n8n trigger loses notifications from a failed Ops Day

Status: needs-triage
Blocked by: None
Source: retail-ops-agent Issue 22 (Review Session Non-critical Finding), triaged in Issue 07

**Where it is now (on `main` at `cfaa54f`):** `src/retail_ops_agent/trigger.py:127-129` (`run_next_day`)

`already_sent` is read at the start of each call. If an Ops Day fails part-way after Intake messaged an Uploader or an alert went out, those notifications stay in `notifier.sent` but the next successful run only returns ones sent during its own call, so they are never forwarded.

- [ ] Track the last forwarded index across calls, with a test.
