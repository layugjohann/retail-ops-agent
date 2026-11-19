# 18: Replay Mode

**What to build:** Record Ops Day outcomes from real runs and play them back in the dashboard with no model and no key, stepping through each stage (Intake, load, detection, Investigation, Actions). It becomes the dashboard's default. Includes a deploy wizard script for the human deploy step in ticket 19.

**Blocked by:** 10

**Status:** in-progress

- [x] Ops Day outcomes can be recorded and stored in the repository
- [x] Replay Mode is the default and makes no model or network calls
- [x] A Visitor can step through a recorded Ops Day stage by stage
- [x] Recordings include at least a Defect day, a stockout with a Reorder, and an Approval
- [x] An interactive wizard script walks the user through deploying to Streamlit Community Cloud
- [x] A dashboard smoke test passes in Replay Mode

## Comments

### Implementer (2026-11-20)

- `retail_ops_agent.replay` records Ops Day outcomes (each stage's results, the BI data loaded, and Approvals taken afterwards) from seeded sandboxes run through the Ops Day boundary, and plays them back stage by stage. Recordings are JSON in `src/retail_ops_agent/recordings/`; `make record` rewrites them.
- The dashboard opens in Replay Mode (sidebar switch to Live Mode, which is the existing seeded sandbox for ticket 20 to build on). Replay Mode never builds a sandbox or Ops Day; the smoke tests block sockets, `build_sandbox` and `OpsDay` with a key set and step through every Recording.
- `make deploy` runs `retail_ops_agent.deploy_wizard`, which checks the repository, offers to make it public, offers to re-record, runs the smoke test, opens Streamlit's deploy page prefilled, and adds the URL to the README. It asks before any push, visibility change or re-record.
- **For ticket 19:** no model key was available when this was built, so the committed Recordings were made with the offline scripted model, and their Investigations say "Not investigated". Before going public, re-record with a free-tier key (`make record`, or let the wizard do it) and commit. The wizard says Streamlit reads dependencies from `uv.lock`/`pyproject.toml`; check on the first deploy that the `retail_ops_agent` package installs there.
- `make` itself could not run in the build sandbox (Xcode shim), so the gate commands were run directly: ruff check, ruff format --check, pyright and pytest (351 passed).

Usage: Implementer 68 input, 48,115 output, 123,484 cache creation, 3,178,399 cache read; Review Session 10 input, 4,803 output, 79,839 cache creation, 370,740 cache read.

**Review Session: Non-critical Findings**

- Committed Recordings were made with the offline scripted model, so every Investigation says 'Not investigated' and recording 02's description ('The Analyst investigates') overstates what the Recording shows; the issue asks for outcomes from real runs. Re-record with a free-tier key before going public (deferred by the Implementer to ticket 19).
- replay.py imports Throttle/ThrottledModel from retail_ops_agent.evals.throttle, so Replay Mode's recording code depends on the eval package; the throttle belongs in a shared module.
- ReplayStep.withdrawn_reorders is populated by replay_step but never rendered by _replay_actions in dashboard/app.py, so a Reorder withdrawn after a Supersede would not be visible in Replay Mode.
- tests/test_replay.py::test_each_stage_shows_only_what_that_stage_did selects the recording by index (load_recordings()[2]), which depends on file-name order; select by recording_id instead.
- sandbox._ran is an unclear name for the on_ops_day callback helper (e.g. _report_ops_day).
- Decision.REJECT and its branch in replay._decide are unused by any RecordingPlan and untested.
- Wizard.start() returns 0 even when the git push in check_repository fails; the failure is printed but not added to the closing notes.

**Gate passed**: every command exited 0 (log: `.sandcastle/logs/gate-18-2026-11-19T16-34-40-056Z.log`).

Usage: Body writer 2 input, 1,694 output, 75,749 cache creation, 11,842 cache read.
