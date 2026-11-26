# 12: Undoing a Safe Fix Quarantines the Upload but tells no one

Status: needs-triage
Blocked by: None
Source: retail-ops-agent Issue 03 (Review Session Non-critical Finding), triaged in Issue 07

**Where it is now (on `main` at `cfaa54f`):** `src/retail_ops_agent/ops_day.py:883-885` (`_settle_upload`)

ADR 0007 says an Upload whose Safe Fix is undone is held in Quarantine until the Uploader resends it. `_settle_upload` only sets the status to `quarantined` and never calls `_message_uploader`, so the Uploader is never asked to resend. Every other route into Quarantine sends a message.

- [ ] Send the Uploader message when an undo Quarantines an Upload, with a test.
