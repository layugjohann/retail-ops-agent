# 36: Replay Mode doesn't show withdrawn Reorders

Status: needs-triage
Blocked by: None
Source: retail-ops-agent Issue 18 (Review Session Non-critical Finding), triaged in Issue 07

**Where it is now (on `main` at `cfaa54f`):** `src/retail_ops_agent/replay.py:138`, `:224`; `dashboard/app.py:741-753` (`_replay_actions`)

`ReplayStep.withdrawn_reorders` is filled by `replay_step` but `_replay_actions` never renders it, so a Reorder withdrawn after a Supersede is invisible in Replay Mode.

- [ ] Render the withdrawn Reorders, with a dashboard test.
