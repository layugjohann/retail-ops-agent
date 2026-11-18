# 05: Resubmission and Superseded Uploads

**What to build:** A later Upload for the same Sales Channel, day and kind replaces the earlier one, which becomes Superseded. A duplicate day inside one file remains a Defect. The generator can produce resubmissions. (Effects further down the pipeline are handled in ticket 15.)

**Blocked by:** 04
**Stacked on:** issue/04-quarantine-and-uploader-messages

**Status:** in-progress

- [ ] Resubmitting replaces the earlier Upload's data in the BI data; nothing is double-counted
- [ ] The earlier Upload's status is Superseded, and the status view shows its history
- [ ] Resubmitting a corrected version of a Quarantined Upload gets it accepted
- [ ] The generator can produce resubmissions (corrected or changed) for a given Upload

## Comments

Usage: Implementer 52 input, 31,001 output, 99,015 cache creation, 2,125,798 cache read; Review Session 12 input, 4,379 output, 52,047 cache creation, 304,920 cache read.

**Review Session: Non-critical Findings**

- run_ops_day only re-scans earlier days that already have a processed Upload (BiStore.upload_days). A late or resubmitted Upload for an earlier day with nothing processed yet is never picked up by a later Ops Day. A resubmission for a day after the `day` argument is also ignored when run_ops_day is called for an earlier day.
- The change adds the domain concept 'resubmission' (ResubmissionPlan, ResubmissionKind corrected/changed, PlantedResubmission) but does not add it to GLOSSARY.md. The project standard requires new domain concepts to be added in the same change.
- ADR 0009 and the new dashboard caption say 'file' ('inside one file', 'resends a corrected file'). 'file' is an Avoid word for Upload in GLOSSARY.md.
- OpsDay.run_ops_day now mixes three jobs: collecting pending Uploads across days, resolving which Upload supersedes which, and Intake/Load. Splitting the pending/supersede resolution into its own helper would keep each function doing one thing.
- In the generator, _revise recomputes a changed row's money column as quantity × retail_price instead of scaling the original net_sales/line_total. If clean rows ever carry discounts, a revised row silently drops them. The ground-truth delta stays consistent, but the revised figure is not 'the same row with more units'.

**Gate passed**: every command exited 0 (log: `.sandcastle/logs/gate-05-2026-11-18T07-17-30-091Z.log`).

Usage: Body writer 2 input, 1,489 output, 42,390 cache creation, 11,615 cache read.
