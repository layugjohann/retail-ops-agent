# 17: Discovery documents and Hours Saved

**What to build:** Simulated discovery documents written as if embedded at Cobalt Home, with a machine-readable baseline of manual timings. The dashboard shows Hours Saved, calculated from the Audit Log and the baseline, with the assumptions next to the number.

**Blocked by:** 03
**Stacked on:** issue/18-replay-mode

**Status:** in-progress

- [ ] An engagement brief based on the job posting's responsibilities, with no company named
- [ ] Personas: store manager, inventory planner, BI analyst, e-commerce lead
- [ ] Current manual processes step by step, and a baseline (task → minutes each time → how often)
- [ ] Every document is labelled as simulated, and every timing cites a public source or is marked as an assumption
- [ ] The baseline is machine-readable; Hours Saved = matching Audit Log entries × baseline minutes, tested through the Ops Day boundary
- [ ] The dashboard shows Hours Saved with its assumptions
- [ ] **The user has reviewed and approved the documents and timings** before this ticket is done

## Comments

Usage: Implementer 52 input, 28,114 output, 91,791 cache creation, 1,957,475 cache read; Review Session 14 input, 3,458 output, 44,574 cache creation, 327,630 cache read.

**Review Session: Non-critical Findings**

- Issue acceptance item 'The user has reviewed and approved the documents and timings' is still open; it needs human review before the ticket is done.
- The investigate-anomaly timing is attributed inconsistently: baseline.json says 'Discovery interviews (simulated)', while docs/discovery/baseline.md cites and links the internal .scratch spec's Problem Statement.
- Safe Fix entries appear to be one per Defect, so an Upload with several Safe-Fixable Defects counts the 10-minute hand-fix several times; the per-Defect counting should be stated in baseline.md or counted per Upload.
- replay_step re-reads baseline.json from disk on every call when no baseline is passed in, and the dashboard calls it on every rerun; could be cached.
- Slightly inconsistent wording of the undo exclusion across baseline.md ('count for nothing') and the dashboard/README ('still stand (not undone)').

**Gate passed**: every command exited 0 (log: `.sandcastle/logs/gate-17-2026-11-19T19-13-25-431Z.log`).

Usage: Body writer 2 input, 1,171 output, 38,048 cache creation, 11,842 cache read.
