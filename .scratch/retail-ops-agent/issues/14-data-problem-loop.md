# 14: Data Problem loop

**What to build:** An Upload reported in cases instead of units passes validation and produces a sales spike. The Analyst concludes Data Problem, the Upload goes back to Intake, which Quarantines it and messages the Uploader. Shows the agents catching each other's misses.

**Blocked by:** 04, 13
**Stacked on:** issue/13-more-anomaly-kinds

**Status:** in-progress

- [ ] The generator can plant a cases-instead-of-units Upload that passes validation
- [ ] Data Problem is a structured conclusion an Investigation can reach
- [ ] A Data Problem conclusion Quarantines the Upload, removes its data from the BI data, and messages the Uploader
- [ ] No business Action (alert or Reorder) is taken for an Anomaly that turned out to be a Data Problem
- [ ] Eval scenarios with the `data-problem` tag are added

## Comments

Usage: Implementer 116 input, 65,277 output, 214,741 cache creation, 8,991,551 cache read; Review Session 18 input, 5,874 output, 67,865 cache creation, 595,587 cache read.

**Review Session: Non-critical Findings**

- Undoing a Data Problem Quarantine reloads the Upload and sets it to accepted, but the units_in_cases Defect added by BiStore.add_defects stays on it. The Upload status view then shows an accepted Upload with a Defect, which conflicts with ADR 0011's 'releases the Upload as it was'.
- In run_ops_day, after a Data Problem unloads Uploads, still_showing filters the original Anomaly objects by anomaly_id. Anomalies that still show are investigated using their first detection's details, whose statistics may have changed once those Uploads left the BI data.
- generator/defects.py keeps the aliases _SKU_COLUMN = SKU_COLUMN and _QUANTITY_COLUMN = QUANTITY_COLUMN instead of using the shared constants from upload_formats directly.

**Gate passed**: every command exited 0 (log: `.sandcastle/logs/gate-14-2026-11-19T10-19-00-942Z.log`).

Usage: Body writer 2 input, 1,671 output, 56,277 cache creation, 11,842 cache read.
