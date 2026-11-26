# 22: `_shut_down_loop` closes a loop that may still be running

Status: needs-triage
Blocked by: None
Source: retail-ops-agent Issue 08 (Review Session Non-critical Finding), triaged in Issue 07

**Where it is now (on `main` at `cfaa54f`):** `src/retail_ops_agent/erp_mcp.py:135-138`

`_shut_down_loop` calls `loop.close()` even if `thread.join(timeout)` returned with the thread still alive, which raises "Cannot close a running event loop" instead of a clear message.

- [ ] Check `is_alive()` after the join and raise an error naming the timeout.
