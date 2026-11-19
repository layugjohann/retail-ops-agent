# Baseline

> **SIMULATED.** Timings for the fictional Client Cobalt Home. Every timing below is an assumption made for this engagement, not a measurement and not taken from a public source.

The machine-readable baseline is
[`src/retail_ops_agent/baseline.json`](../../src/retail_ops_agent/baseline.json); this table is the
same data for reading. Hours Saved counts, for each task, the Audit Log entries of its Action that
still stand (undos and undone entries count for nothing) and multiplies them by the minutes each
time.

| task_id | task | persona | Audit Log Action | minutes each | how often | basis |
| --- | --- | --- | --- | --- | --- | --- |
| fix-small-upload-defect | Find and correct a small Upload Defect by hand, reload it and check its totals | BI analyst | `safe_fix` | 10 | about 1 a day | assumption |
| chase-unfixable-upload | Diagnose an Upload that cannot be fixed without asking, write to the Uploader, chase the resend and load it | BI analyst | `quarantine` | 25 | about 3 a week | assumption |
| investigate-anomaly | Notice an Anomaly, work out its likely cause and tell the person who should act | BI analyst | `alert` | 45 | about 2 a week | assumption |
| key-in-reorder | Work out a Reorder quantity and key the Reorder into the ERP | inventory planner | `reorder` | 15 | about 3 a week | assumption |

## Why these numbers

- **fix-small-upload-defect, 10 minutes.** Open the file, find the cause, edit, re-import, compare
  totals with the day before. Assumes the analyst is not interrupted.
- **chase-unfixable-upload, 25 minutes.** Diagnosis, a message the Uploader can act on, follow-up
  questions and reloading the resend, spread over the day. The Uploader's own time is not counted.
- **investigate-anomaly, 45 minutes.** The [Problem Statement](../../.scratch/retail-ops-agent/spec.md)
  describes this as "most of an hour". Pulling history, comparing Sales Channels, checking the ERP
  and writing it up.
- **key-in-reorder, 15 minutes.** About 17 minutes by hand, less a minute or two the inventory
  planner still spends on the Approval. The Investigation behind a Reorder is not counted, so the
  figure is conservative.

## What is left out

- Totalling the Online Shop's Order Lines and renaming its stock columns (process 5 in
  [Current manual processes](manual-processes.md)): no Audit Log Action records it.
- The time Uploaders spend resending files, and the cost of decisions taken late.
- Replacing, withdrawing and undoing Actions: these are housekeeping, not manual work saved.

## At the stated frequencies

Illustrative only, from the assumed frequencies: 7 × 10 + 3 × 25 + 2 × 45 + 3 × 15 = 280 minutes,
about 4.7 hours a week. The dashboard does not use this figure: it counts what the Audit Log shows
actually happened.

## Before trusting these numbers

Time each task with the person who does it, for a week, and replace the assumption with the
measurement (`"basis": "source"` with the measurement named in `"source"`). The Deployment
Playbook describes this.
