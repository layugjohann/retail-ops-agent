# 03: Safe Fixes and the Audit Log

**What to build:** The generator can plant Defects that have a Safe Fix and record each one in a ground-truth record. Intake detects them and applies the Safe Fix. Every Safe Fix is written to an append-only Audit Log entry that includes how to undo it, and undo works through the Ops Day boundary. The dashboard gets an Audit Log view with undo.

**Blocked by:** 01
**Stacked on:** issue/02-all-upload-formats

**Status:** in-progress

- [ ] A fixed table, not the model, decides which Defect kinds have a Safe Fix
- [ ] At least the obvious safe-fixable Defects (for example renamed headers that match unambiguously, stray whitespace, a trivial delimiter issue) are planted, detected and fixed
- [ ] The generator writes a ground-truth record (Upload, Defect kind, location, expected outcome)
- [ ] Each Safe Fix creates an Audit Log entry recording what triggered it, who took it, its Tier (1) and how to undo it
- [ ] Undo is an Ops Day operation; it restores the original data and is recorded as a new entry, never an edit
- [ ] Clean Uploads produce no Safe Fixes
- [ ] The dashboard Audit Log view lists entries and can trigger undo

## Comments

Usage: Implementer 60 input, 47,691 output, 112,625 cache creation, 2,755,275 cache read; Review Session 8 input, 6,215 output, 54,328 cache creation, 200,562 cache read.

**Review Session: Non-critical Findings**

- safe_fixes.apply_safe_fixes applies the byte-order-mark, delimiter, rename and whitespace fixes unconditionally and only checks SAFE_FIX_TABLE afterwards with an `assert`. The table never decides whether a fix runs. If a kind is set to False in the table, Intake crashes instead of Quarantining, and under `python -O` the table is ignored completely. Each fix should be gated with has_safe_fix(kind) so that a non-safe kind is reported as a Defect.
- Undoing a Safe Fix moves the Upload to Quarantine (ADR 0007: 'held in Quarantine until the Uploader resends it'), but no Notifier message is sent. The Uploader is never told to resend. Every other route into Quarantine sends one.
- OpsDay.undo appends the undo entry before _settle_safe_fixes changes the BI data and status, outside any transaction. If settling fails (for example, the Upload is no longer in the Data Source), the log records an undo that never took effect.
- AuditLog.append calls entry(), which calls entries() and rebuilds the whole log, so every append costs O(n). _settle_safe_fixes also reads the whole log for each undo.
- In _settle_safe_fixes, the comment 'Safe Fixes are deterministic, so reading the Upload again gives the rows first loaded' assumes the model reported no extra Defects. The reload uses parse_upload directly and skips run_intake, so this only holds because an Upload with model-reported Defects is never Safe-Fixed. The assumption is implicit.
- New domain concepts (the Action Tier names READ/INTERNAL/EXTERNAL, the undo recipe, and 'reinstate') are not added to GLOSSARY.md; only Ground Truth was added.
- The generator's _RENAMES list and safe_fixes.COLUMN_ALIASES are two hand-kept lists that must stay in step, and nothing tests that every planted alias is recognised. Today they agree only because the parametrised test happens to hit the variants the RNG picks.

**Gate passed**: every command exited 0 (log: `.sandcastle/logs/gate-03-2026-11-18T06-53-58-608Z.log`).

Usage: Body writer 2 input, 1,746 output, 48,135 cache creation, 11,615 cache read.
