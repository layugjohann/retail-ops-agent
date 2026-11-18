# Undoing a Quarantine releases only the rows that passed every check

A Quarantine is a Tier 1 Action with its own Audit Log entry. Undoing it releases the Upload: the rows that passed every check (with any Safe Fixes applied) are loaded into the BI data, and the Upload is accepted (or Safe-Fixed). Rows that have a Defect stay out, and so does every repeated row of a duplicated day, because loading them would mean guessing at a value nobody supplied. A Defect in the header, such as a missing or swapped column, leaves no rows that passed, so releasing such an Upload loads nothing. If the release is itself undone, the Upload goes back into Quarantine and its rows leave the BI data again.

The Uploader message lists each Defect with its location and the correction to make, from fixed tables. The Intake agent can add a note of its own, but the list is always there, so every message says what is wrong, where, and what to do, however weak the model is.

## Consequences

An Upload's status follows from the Audit Log: it is Quarantined while its Quarantine stands or any of its Safe Fixes is undone, and loaded otherwise. Releasing is for a BI analyst who disagrees with Intake. The usual route out of Quarantine is still a corrected Upload from the Uploader.
