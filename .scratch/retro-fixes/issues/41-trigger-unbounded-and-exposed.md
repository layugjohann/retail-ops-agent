# 41: The trigger's `/inbox` is unbounded and the README suggests binding 0.0.0.0

Status: needs-triage
Blocked by: None
Source: retail-ops-agent Issue 22 (Review Session Non-critical Finding), triaged in Issue 07

**Where it is now (on `main` at `cfaa54f`):** `src/retail_ops_agent/trigger.py:113`, `:225-235`; `README.md:229`

`POST /inbox` reads a body of any `Content-Length` and keeps every JSON object in memory, and no endpoint is authenticated. The README tells Linux users to bind `--host 0.0.0.0` with no warning that this exposes `/ops-day/run` and `/inbox` to the network.

- [ ] Cap the body size and inbox length, and warn in the README (or bind to the Docker bridge address instead).
