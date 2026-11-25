# 01: Fix the bugs left in Review Findings

Status: in-progress
Blocked by: None

**What to build:** Fix the bugs that Review Sessions logged as Non-critical Findings and that are still on `main`.
Each fix comes with a test that fails without it (coding standard). Check each one still reproduces before fixing it.
If it doesn't, say so in a comment and skip it.

- [x] **Expired Reorders warning never shows** (Issue 11). `dashboard/app.py` around line 330 calls
      `st.warning("Expired: ...")` and then `st.rerun()` straight away, so the warning is wiped before anyone sees it.
      Keep the message across the rerun (for example in `st.session_state`) and show it on the next render.
- [x] **The Safe Fix table doesn't decide which fixes run** (Issue 03). `safe_fixes.apply_safe_fixes` applies the
      byte-order-mark, delimiter, rename and whitespace fixes unconditionally, and only checks `SAFE_FIX_TABLE`
      afterwards with an `assert` (`safe_fixes.py` around line 108). Gate each fix on `has_safe_fix(kind)`, so a kind
      set to `False` sends the Upload to Quarantine instead of crashing, also under `python -O`.
- [x] **Undoing a Reorder leaves it `approved`** (Issue 10). Undoing a Reorder's Audit Log entry cancels it in the ERP,
      but its Approval Queue item keeps `approved` / `auto_approved`, so `OpsDay.reorders()` and the dashboard still
      show it as placed.
- [x] **A released Data Problem Quarantine keeps its Defect** (Issue 14). Undoing it reloads the Upload as `accepted`,
      but the `units_in_cases` Defect added by `BiStore.add_defects` stays, which conflicts with ADR 0011
      ("releases the Upload as it was").
- [x] **Dead code** (Issue 13): `SKU_KINDS` in `src/retail_ops_agent/anomalies.py` is never used. Delete it.

## Comments

**Implementer:** All five still reproduced on `main`, and all five are fixed. Each fix has a test that fails without it.

- Expired warning: the message waits in `st.session_state` and the next render shows it once. The existing
  dashboard test assumed the Reorder Expires on the second advance; it Expires on the first, so the test now
  checks the warning there and checks it is gone after the next advance.
- Safe Fix table: each fix runs only if `has_safe_fix(kind)`. Otherwise `apply_safe_fixes` reports the Defect in a
  new `unfixed` list, which `parse_upload` counts as a Defect, so the Upload goes to Quarantine. The `assert` is gone.
- Undone Reorder: a new `ApprovalStatus.CANCELLED`, with `cancelled_by` / `cancelled_at`. The Approval and the ERP
  Reorder id stay on the item. The `approval_queue` eval grader treats `cancelled` as placed. The dashboard's
  Decided Reorders table has a "cancelled by" column.
- Released Data Problem Quarantine: `_settle_upload` keeps the Data Problem's Defect only while its Quarantine
  stands (new `BiStore.remove_defects`). Undoing the undo brings the Defect back.
- `SKU_KINDS` deleted.

Usage: Implementer unknown; Review Session unknown.

**Review Session: Non-critical Findings**

- ApprovalStatus.CANCELLED (with cancelled_by / cancelled_at) is a new Approval Queue state but has no GLOSSARY.md entry, and GLOSSARY.md lists 'cancelled' as an Avoid word under Expired. Add a glossary entry that tells a cancelled-by-undo Reorder apart from an Expired one.
- OpsDay._settle_upload removes and re-adds each Data Problem Quarantine's Defect in Audit Log order. If two Data Problem Quarantines on one Upload carried the same Defect, and the earlier one stood while the later one was undone, the Defect would be dropped. This doesn't look reachable today, but the logic is order-dependent.
- BiStore.remove_defects repeats add_defects's 'SELECT defects ... / KeyError if missing' lookup; a small shared helper would remove the duplication.

**Gate passed**: every command exited 0 (log: `.sandcastle/logs/gate-01-2026-11-25T14-16-56-129Z.log`).

Usage: Body writer 2 input, 1,685 output, 20,639 cache creation, 11,837 cache read.
