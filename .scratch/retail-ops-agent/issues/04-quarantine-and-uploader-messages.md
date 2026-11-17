# 04: Quarantine and Uploader messages

**What to build:** Defects without a Safe Fix put the Upload into Quarantine, keeping it out of the BI data entirely, and Intake writes the Uploader a plain-language message (through the Notifier) saying what is wrong, where, and what to do. The Upload status view shows Quarantine.

**Blocked by:** 03

**Status:** ready-for-agent

- [ ] Planted unfixable Defects (missing column, ambiguous swapped columns, duplicate day in one file, impossible quantity, unknown SKU, date mismatch) each lead to Quarantine
- [ ] None of a Quarantined Upload's rows appear in the BI data
- [ ] A clean Upload is never Quarantined
- [ ] The Notifier interface exists with a log implementation; the Uploader message is part of the Ops Day outcome and visible on the dashboard
- [ ] The message names the Defect, its location, and the fix to make
- [ ] Quarantine is a Tier 1 Action in the Audit Log and can be undone

## Comments
