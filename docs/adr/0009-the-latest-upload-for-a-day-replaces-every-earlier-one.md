# The latest Upload for a Sales Channel, day and kind replaces every earlier one

When an Upload arrives for a Sales Channel, day and kind that already has one, the later Upload replaces the earlier one whatever happened to it. The earlier Upload becomes Superseded: its rows leave the BI data, it stays in the Upload status view with the Upload that replaced it, and the history of its statuses is kept in the BI store. So a resubmission is never double-counted and never flagged as a duplicate. A day reported twice *inside one file* is still a Defect, because nothing says which copy the Uploader meant.

The later Upload replaces the earlier one even if the later one is Quarantined. Keeping the earlier data instead would mean guessing that the Uploader still stands by figures they have just resent; the Uploader is messaged about the Quarantine and resends a corrected file, as with any Quarantine. If several Uploads for the same Sales Channel, day and kind arrive before an Ops Day runs, only the latest goes through Intake; the others are recorded as Superseded straight away. An Ops Day also picks up resubmissions for earlier days that have already had an Ops Day.

## Consequences

The Audit Log entries of a Superseded Upload (its Safe Fixes and Quarantine) can no longer be undone: undoing them would bring back data an Uploader has replaced. Superseding is not itself an Action in the Audit Log; it follows from the Uploader's own resubmission. What Supersede does further down the pipeline (re-checking Anomalies, undoing dependent Tier 1 Actions, flagging Tier 2 Actions) is ticket 15.
