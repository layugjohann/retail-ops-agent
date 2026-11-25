# 01: Fix the bugs left in Review Findings

Status: ready-for-agent
Blocked by: None

**What to build:** Fix the bugs that Review Sessions logged as Non-critical Findings and that are still on `main`.
Each fix comes with a test that fails without it (coding standard). Check each one still reproduces before fixing it.
If it doesn't, say so in a comment and skip it.

- [ ] **Expired Reorders warning never shows** (Issue 11). `dashboard/app.py` around line 330 calls
      `st.warning("Expired: ...")` and then `st.rerun()` straight away, so the warning is wiped before anyone sees it.
      Keep the message across the rerun (for example in `st.session_state`) and show it on the next render.
- [ ] **The Safe Fix table doesn't decide which fixes run** (Issue 03). `safe_fixes.apply_safe_fixes` applies the
      byte-order-mark, delimiter, rename and whitespace fixes unconditionally, and only checks `SAFE_FIX_TABLE`
      afterwards with an `assert` (`safe_fixes.py` around line 108). Gate each fix on `has_safe_fix(kind)`, so a kind
      set to `False` sends the Upload to Quarantine instead of crashing, also under `python -O`.
- [ ] **Undoing a Reorder leaves it `approved`** (Issue 10). Undoing a Reorder's Audit Log entry cancels it in the ERP,
      but its Approval Queue item keeps `approved` / `auto_approved`, so `OpsDay.reorders()` and the dashboard still
      show it as placed.
- [ ] **A released Data Problem Quarantine keeps its Defect** (Issue 14). Undoing it reloads the Upload as `accepted`,
      but the `units_in_cases` Defect added by `BiStore.add_defects` stays, which conflicts with ADR 0011
      ("releases the Upload as it was").
- [ ] **Dead code** (Issue 13): `SKU_KINDS` in `src/retail_ops_agent/anomalies.py` is never used. Delete it.
