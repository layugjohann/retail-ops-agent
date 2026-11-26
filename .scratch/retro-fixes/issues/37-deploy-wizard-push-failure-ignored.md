# 37: The deploy wizard ends with success when `git push` failed

Status: needs-triage
Blocked by: None
Source: retail-ops-agent Issue 18 (Review Session Non-critical Finding), triaged in Issue 07

**Where it is now (on `main` at `cfaa54f`):** `src/retail_ops_agent/deploy_wizard.py:151-152`, `:118`

When the push in `check_repository` fails, the wizard prints "Push failed" and carries on; nothing is added to `self.notes` and `start()` returns 0, so the closing summary reads as success.

- [ ] Add the failure to the closing notes (or stop), and return non-zero.
