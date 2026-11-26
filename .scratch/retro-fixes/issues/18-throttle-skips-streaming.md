# 18: `ThrottledModel` does not pace or retry streamed requests

Status: needs-triage
Blocked by: None
Source: retail-ops-agent Issue 07 (Review Session Non-critical Finding), triaged in Issue 07

**Where it is now (on `main` at `cfaa54f`):** `src/retail_ops_agent/evals/throttle.py:111-197`

`ThrottledModel` only overrides `request`. `request_stream` and `count_tokens` go straight to the wrapped model with no pacing and no 429/503 retry. Nothing streams today, but `models.py` uses the wrapper outside evals too, so a future streaming agent would silently lose throttling.

- [ ] Wrap `request_stream` too, or make it raise, with a test.
