# 05: Resubmission and Superseded Uploads

**What to build:** A later Upload for the same Sales Channel, day and kind replaces the earlier one, which becomes Superseded. A duplicate day inside one file remains a Defect. The generator can produce resubmissions. (Effects further down the pipeline are handled in ticket 15.)

**Blocked by:** 04

**Status:** ready-for-agent

- [ ] Resubmitting replaces the earlier Upload's data in the BI data; nothing is double-counted
- [ ] The earlier Upload's status is Superseded, and the status view shows its history
- [ ] Resubmitting a corrected version of a Quarantined Upload gets it accepted
- [ ] The generator can produce resubmissions (corrected or changed) for a given Upload

## Comments
