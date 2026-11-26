# 38: A Visitor's own CSV is decoded with `errors="replace"`

Status: needs-triage
Blocked by: None
Source: retail-ops-agent Issue 20 (Review Session Non-critical Finding), triaged in Issue 07

**Where it is now (on `main` at `cfaa54f`):** `dashboard/app.py:156`

Invalid bytes in a Visitor's Upload become U+FFFD before Intake sees them, so an encoding Defect the Visitor plants is silently changed instead of flagged.

- [ ] Pass the raw bytes (or decode strictly) so Intake reports the encoding Defect.
