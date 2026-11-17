# 03: Safe Fixes and the Audit Log

**What to build:** The generator can plant Defects that have a Safe Fix and record each one in a ground-truth record. Intake detects them and applies the Safe Fix. Every Safe Fix is written to an append-only Audit Log entry that includes how to undo it, and undo works through the Ops Day boundary. The dashboard gets an Audit Log view with undo.

**Blocked by:** 01

**Status:** ready-for-agent

- [ ] A fixed table, not the model, decides which Defect kinds have a Safe Fix
- [ ] At least the obvious safe-fixable Defects (for example renamed headers that match unambiguously, stray whitespace, a trivial delimiter issue) are planted, detected and fixed
- [ ] The generator writes a ground-truth record (Upload, Defect kind, location, expected outcome)
- [ ] Each Safe Fix creates an Audit Log entry recording what triggered it, who took it, its Tier (1) and how to undo it
- [ ] Undo is an Ops Day operation; it restores the original data and is recorded as a new entry, never an edit
- [ ] Clean Uploads produce no Safe Fixes
- [ ] The dashboard Audit Log view lists entries and can trigger undo

## Comments
