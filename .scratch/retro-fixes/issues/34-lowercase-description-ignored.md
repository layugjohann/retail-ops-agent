# 34: A lowercase `description` header in the Stock Snapshot is silently ignored

Status: needs-triage
Blocked by: None
Source: retail-ops-agent Issue 16 (Review Session Non-critical Finding), triaged in Issue 07

**Where it is now (on `main` at `cfaa54f`):** `src/retail_ops_agent/upload_formats.py:62`, `:181`, `:213-220`; `src/retail_ops_agent/safe_fixes.py:159-175`

The Online Shop Stock Snapshot's free-text header must be exactly `Description`. A `description` column is neither quoted to the model nor reported, because renames apply only to expected columns. Harmless, but unlike how other renamed headers are handled.

- [ ] Recognise the free-text header case-insensitively, or report it.
