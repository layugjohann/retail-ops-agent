# Undoing a Safe Fix puts the Upload back as it arrived, in Quarantine

Each Safe Fix gets its own Audit Log entry, and any of them can be undone. Undoing one does not try to load the Upload with just that one correction left out. The Upload goes back to how it arrived: its rows leave the BI data and, because it now has a Defect with no fix applied, it is held in Quarantine until the Uploader resends it. Loading a partly fixed Upload would mean guessing what the Uploader meant by the Defect someone just rejected, which is the guess a Safe Fix exists to avoid. If an undo is itself undone, the Safe Fixes are applied again. They are deterministic, so the Upload loads exactly as it first did.

Renames are also conservative. A renamed header is fixed only if every expected column can then be found. If a header would still be missing columns after renaming, it is some other layout, and it is Quarantined unchanged.

## Consequences

The Audit Log is append-only. Whether an entry is undone is worked out when the log is read: an entry is undone while an undo of it exists that has not been undone itself. An Upload's status (`safe_fixed` or `quarantined`) follows from whether all of its Safe Fixes still stand.
